#!/usr/bin/env python2.7
import sys
from zipfile import ZipFile
from xml.dom.minidom import parseString
from hashlib import sha256

TMPL = """<?xml version="1.0"?>
<RDF xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:em="http://www.mozilla.org/2004/em-rdf#"><Description about="urn:mozilla:extension:dta@downthemall.net"><em:updates><Seq><li><Description>
<em:version/>
</Description></li></Seq></em:updates></Description></RDF>
"""

_,xpi,out,url = sys.argv
with open(xpi, "rb") as ip:
  xh = sha256(ip.read()).hexdigest()
rdf = parseString(TMPL)
xpi = ZipFile(xpi)
inrdf = parseString(xpi.read("install.rdf"))
ver = inrdf.getElementsByTagName("em:version")[0]

el = rdf.getElementsByTagName("em:version")[0]
el.appendChild(rdf.createTextNode(ver.firstChild.nodeValue))
el = el.parentNode

for ta in inrdf.getElementsByTagName("em:targetApplication"):
  d = ta.getElementsByTagName("Description")[0]
  ul = rdf.createElement("em:updateLink")
  ul.appendChild(rdf.createTextNode(url))
  d.appendChild(ul)
  uh = rdf.createElement("em:updateHash")
  uh.appendChild(rdf.createTextNode("sha256:{0}".format(xh)))
  d.appendChild(uh)
  el.appendChild(ta)

with open(out, "wb") as op:
  op.write(rdf.toxml())
