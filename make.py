#!/bin/env python
"""
Small python make tool for XPIs using SVN.
(C) 2007 Nils Maier
Licensed under MPL1.1/GPL2.0/LGPL2.1
"""
from __future__ import with_statement

import os, re, sys
import tarfile

try:
    import pysvn as svn
except:
    print 'pysvn required: http://pysvn.tigris.org/'
    sys.exit(1)

from httplib import HTTPConnection
from os import path
from shutil import rmtree
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from urlparse import urlparse
from xml.dom.minidom import parse as xml_open
from time import strftime

NS_RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
NS_EM  = 'http://www.mozilla.org/2004/em-rdf#'

BLOCK_START = "***** BEGIN LICENSE BLOCK *****"
BLOCK_END = "***** END LICENSE BLOCK *****"

block_replacement = "You may find the license in the LICENSE file"
svn_path = 'http://code.downthemall.net/repos/'
locales_url = 'http://www.babelzilla.org/components/com_wts/com_download.php?extension=1455&type=all'
locales_headers = {}
locales_file = 'locales.tar.gz'

signtool = 'signtool'
if os.name == 'nt':
    signtool = 'signtool/signtool.exe'

xpi_file = 'downthemall.xpi'

def keysigned(f):
    if re.search("meta-inf", f, re.I):
        return u"0" + f
    return u"1" + f

class XPI:
    rev = None
    
    def __init__(self, opts, repos, exportTo='export'):
        self.client = svn.Client()
        self.opts = opts
        self.opts.branch = repos + opts.branch + "/"
        self.opts.exportTo = exportTo
        
    def create(self, xpi_file):
        global locales_url, locales_headers
        yield "preparing"
        self.prepare()
        yield "checking out"
        self.checkout()
        if self.opts.locget:
            yield "getting locales"
            self.getlocales(locales_url, locales_headers, locales_file, self.opts.locget)
        if self.opts.locint or self.opts.locget:
            yield "integrating locales"
            self.integratelocales(locales_file)
        if self.opts.nightly:
            yield "nightlifying"
            self.nightlify()
        if self.opts.extid and not self.opts.extid == 'default':
            yield "setting the extension id"
            self.setId()
        if self.opts.nocomments:
            yield "stripping comments"
            self.stripcomments()
        if self.opts.release:
            yield "jarring"
            self.jar()
        if self.opts.signkey:
            yield "signing with key " + self.opts.signkey
            self.sign()
        yield "creating the xpi"
        for x in self.createXPI(xpi_file, self.opts.rc):
            yield x
        yield "cleaning up"
        self.cleanup()

    def prepare(self):
        if path.isdir(self.opts.exportTo):
            rmtree(self.opts.exportTo)
    def checkout(self):
        self.client.export(self.opts.branch, self.opts.exportTo, True)

    def getlocales(self, url, headers, filename, cookie):
        if path.isfile(filename):
            os.remove(filename)
        if not headers:
            headers = dict()
        if cookie:
            headers['Cookie'] = cookie

        url = urlparse(url)
        http = HTTPConnection(url.hostname, url.port)
        http.request('GET', "%s?%s" % (url.path, url.query), None, headers)
        r = http.getresponse()
        f = open(filename, 'wb')
        f.write(r.read())
        f.close()
        http.close()

    def integratelocales(self, filename):
        tar = tarfile.open(filename)
        localedir = '%s/chrome/locale/' % self.opts.exportTo
        tar.extractall(localedir)

        man = open("export/chrome.manifest", 'ab')
        man.write("# integrated locales:\n")
        
        for x in os.listdir(localedir):
            if not re.match(r'\w+-\w+$', x):
                continue
            if x == 'en-US':
                continue
            man.write('locale\tdta\t%s\tchrome/locale/%s/\n' % (x, x))
        man.close()

    def getrevision(self):
        if not self.rev:
            self.rev = self.client.info2(self.opts.branch, recurse=False)[0][1].rev.number
        return self.rev
        

    def nightlify(self):
        'open'
        rdf = xml_open('%s/install.rdf' % self.opts.exportTo)

        'update the version'
        node = rdf.getElementsByTagNameNS(NS_EM, 'version')[0].childNodes[0]
        node.data = "%s.%s.%s" % (node.data, strftime("%Y%m%d"), self.getrevision())

        node = rdf.getElementsByTagNameNS(NS_EM, 'name')[0].childNodes[0]
        node.data = node.data + ' *nightly*'

        'insert the updateURL node'
        node = rdf.getElementsByTagNameNS(NS_EM, 'aboutURL')[0]
        u = rdf.createElementNS(NS_EM, 'em:updateURL')
        u.appendChild(rdf.createTextNode(self.opts.updateURL))
        node.parentNode.insertBefore(u, node)

        'prettify'
        node.parentNode.insertBefore(rdf.createTextNode('\n\t\t'), node)

        'save'
        with open('export/install.rdf', 'w') as f:
            f.write(rdf.toxml(encoding="utf-8"))

        'cleanup'
        rdf.unlink()

    def setId(self):
        rdf = xml_open('%s/install.rdf' % self.opts.exportTo)

        'update the id'
        node = rdf.getElementsByTagNameNS(NS_EM, 'id')[0].childNodes[0]
        node.data = self.opts.extid

        'save'
        f = open('export/install.rdf', 'w')
        rdf.writexml(f)

        'cleanup'
        rdf.unlink()
        f.close()

        for vi in ('modules/version.jsm', 'chrome/content/common/verinfo.js'):
            vi = '%s/%s' % (self.opts.exportTo, vi)
            if not os.path.exists(vi):
                continue
            f = open(vi)
            lines = f.readlines()
            f.close()
            f = open(vi, 'wb')
            for l in lines:
                if re.search('const ID', l):
                    l = "const ID = '%s';\n" % self.opts.extid
                elif re.search('const DTA_ID', l):
                    l = "const DTA_ID = '%s';\n" % self.opts.extid
                f.write(l)
            f.close()
            
    def jar(self):
        f = open('%s/chrome.manifest' % self.opts.exportTo)
        lines = f.readlines()
        f.close()
        f = open('%s/chrome.manifest' % self.opts.exportTo, 'wb')
        for l in lines:
            l = re.sub(r'(\s)chrome/', r'\1jar:chrome/chrome.jar!/', l);
            f.write(l)
        f.close()

        p = self.opts.exportTo +  "/chrome"
        dc = os.listdir(p)[:]
        dirs = ()
        for x in dc:
            if x in ('icons'):
                continue
            f = p + "/" + x
            if path.isdir(f):
                dirs += f,
        jar_file = ZipFile(p + "/chrome.jar", 'w', ZIP_STORED)
        for d in dirs:
            for x in self.getfilelist(d):
                jar_file.write(x, x[len(p) + 1:].encode('cp437'))
            rmtree(d)
        jar_file.close()


    def _getfilelist(self, p):
        l = os.listdir(p)[:]
        for x in l:
            f = p + "/" + x
            if path.isfile(f):
                yield unicode(f)
            elif path.isdir(f):
                for i in self._getfilelist(f):
                    yield i
                    
    def _getfilelistsigned(self, manifest):
        rv = ['META-INF/zigbert.rsa']
        with open(manifest, 'r') as mf:
            for line in mf:
                m = re.match(r'^Name: (.+)$', line)
                if not m:
                    continue
                rv += m.group(1),
        rv += ['META-INF/manifest.mf', 'META-INF/zigbert.sf']
        return map(lambda x: os.path.join(self.opts.exportTo, x), rv)

    def getfilelist(self, p):
        manifest = os.path.join(self.opts.exportTo, 'META-INF/manifest.mf')
        if os.path.exists(manifest):
            return self._getfilelistsigned(manifest)
        return sorted(self._getfilelist(p))

    def stripcomments(self):
        global BLOCK_START, BLOCK_END, block_replacement
        replacement = r'%s.+%s' % (re.escape(BLOCK_START), re.escape(BLOCK_END))
        replacement = re.compile(replacement, re.S | re.M)
        mask = re.compile(r'\.(xul|xml|dtd|jsm?)$', re.I)
        for f in self.getfilelist(self.opts.exportTo):
            if not mask.search(f):
                continue
            p = open(f, 'rb')
            c = p.read()
            p.close()
            c = replacement.sub(block_replacement, c)
            p = open(f, 'wb')
            p.write(c)
            p.close()

    def sign(self):
        if os.spawnl(os.P_WAIT, signtool, signtool, '-d', '.', '-k', "\"%s\"" % self.opts.signkey, self.opts.exportTo):
            raise Exception("Signing failed!")
        
    def createXPI(self, xpi_file, rc):
        additional = ''

        if self.opts.version:
            rdf = xml_open('%s/install.rdf' % self.opts.exportTo)
            additional += '-' + rdf.getElementsByTagNameNS(NS_EM, 'version')[0].childNodes[0].data
            if rc > 0:
                additional += "rc%d" % rc
            rdf.unlink()
        if self.opts.revision:
            additional += '-r%d' % self.getrevision()
        output = xpi_file % additional
        xpi_file = ZipFile(output, 'w', ZIP_DEFLATED)
        for x in self.getfilelist(self.opts.exportTo):
            yield x
            xpi_file.write(x, x[len(self.opts.exportTo) + 1:].encode('cp437'))
        xpi_file.close()
        yield "written to: " + output

    def cleanup(self):
        if path.isdir(self.opts.exportTo):
            rmtree(self.opts.exportTo)

def main():
    global xpi_file, svn_path
    
    parser = OptionParser(usage="%prog [options] [branch]", version="$Id: make.py 2111 2010-10-14 13:54:45Z MaierMan $")
    parser.add_option(
        '--locint',
        dest='locint',
        help='integrate locales',
        action='store_true',
        default=False
        )
    parser.add_option(
        '--locget',
        dest='locget',
        help='download locales (provide your babelzilla auth cookie). Implies --locint',
        action='store',
        type='string',
        default=''
        )
    parser.add_option(
        '--addversion',
        dest='version',
        help='add version to filename',
        action='store_true',
        default=False
        )
    parser.add_option(
        '--addrevision',
        dest="revision",
        help="adds the SVN revision to the filename",
        action="store_true",
        default=False
        )
    parser.add_option(
        '--nightly',
        dest='nightly',
        help='is a nightly',
        action="store_true",
        default=False
        )
    parser.add_option(
        '--updateURL',
        dest='updateURL',
        help='The update url of the nightly build',
        type="string"
        )
    parser.add_option(
        '--release',
        dest='release',
        help='Is a release',
        action='store_true',
        default=False
        )
    parser.add_option(
        '--extid',
        dest='extid',
        help='Set the extension id',
        type='string'
        )    
    parser.add_option(
        '--nocomment',
        dest='nocomments',
        help='collapse those comment blocks',
        action='store_true',
        default=False
        )
    parser.add_option(
        '--quiet',
        dest="quiet",
        help="don't display info messages",
        action="store_true",
        default=False
        )
    parser.add_option(
        '--output',
        dest='xpifile',
        help='the resulting xpi file (might be changed by the modificators)',
        type='string',
        default=xpi_file
        )
    parser.add_option(
        '--rc',
        dest='rc',
        help='the resulting xpi file (might be changed by the modificators)',
        type='int',
        default=0
        )
    parser.add_option(
        '--sign',
        dest="signkey",
        help="sign with this key",
        type="string"
        )
    opts, args = parser.parse_args()
    if len(args) > 1:
        parser.error("provide exactly one branch!")
    elif len(args) == 0:
        args = ['trunk']

    if re.match('^release', args[0]) and not opts.extid:
        parser.error("making a release with default extid! Specify 'default' to use default id instead")
        sys.exit(1)

    if opts.nightly and not opts.updateURL:
        parser.error("when building nightlies you must provide an updateURL")
        sys.exit(1)

    opts.branch, = args

    xpi_file = "%s%%s%s" % path.splitext(opts.xpifile)

    xpi = XPI(opts, svn_path)
    for x in xpi.create(xpi_file):
        if not opts.quiet:
            print x

if __name__ == "__main__":
    from optparse import OptionParser
    main()
