"""
Debug script - run this to inspect the actual XML structure of a Word document
Usage: python debug_doc.py path/to/file.docx
"""
import sys
from docx import Document
from lxml import etree

filepath = sys.argv[1] if len(sys.argv) > 1 else input("Enter docx path: ")
doc = Document(filepath)
section = doc.sections[0]
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
ns = {'w': W}

print("=== PAGE SIZE ===")
print(f"  page_width  = {section.page_width}  (A4 target: 11906200)")
print(f"  page_height = {section.page_height}  (A4 target: 16838040)")

print("\n=== MARGINS ===")
print(f"  top={section.top_margin}  bottom={section.bottom_margin}  left={section.left_margin}  right={section.right_margin}  (2.5cm target: ~914400)")

print("\n=== PAGE BORDERS (raw XML) ===")
borders = doc._element.xpath('//w:sectPr/w:pgBorders', namespaces=ns)
if borders:
    print(etree.tostring(borders[0], pretty_print=True).decode())
else:
    print("  No pgBorders found")

print("\n=== HEADER XML ===")
header = doc.sections[0].header
if header:
    print(etree.tostring(header._element, pretty_print=True).decode()[:3000])
else:
    print("  No header")

print("\n=== FOOTER XML ===")
footer = doc.sections[0].footer
if footer:
    print(etree.tostring(footer._element, pretty_print=True).decode()[:3000])
else:
    print("  No footer")

print("\n=== SETTINGS XML (hyphenation) ===")
try:
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    settings_part = doc.part.part_related_by('http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings')
    settings_xml = etree.tostring(settings_part._element, pretty_print=True).decode()
    if 'Hyphen' in settings_xml or 'hyphen' in settings_xml:
        for line in settings_xml.splitlines():
            if 'hyphen' in line.lower():
                print(" ", line.strip())
    else:
        print("  No hyphenation settings found")
        print("  (first 500 chars):", settings_xml[:500])
except Exception as e:
    print(f"  Error reading settings: {e}")
    # Try alternate method
    doc_xml = doc._element
    settings = doc_xml.xpath('//w:settings', namespaces=ns)
    print(f"  xpath //w:settings found: {len(settings)} results")
    if settings:
        xml_str = etree.tostring(settings[0], pretty_print=True).decode()
        print("  Settings XML (first 1000):", xml_str[:1000])
