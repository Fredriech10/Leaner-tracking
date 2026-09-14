"""Hyperlink rule checker for Word documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZipFile

from docx import Document
from lxml import etree

from ..checker_types import CheckerResult


def check_hyperlink_rule(rule: Dict[str, Any], file_path: Path) -> CheckerResult:
    document = Document(file_path)
    check_type = str(rule.get("type", ""))
    expected = rule.get("expected")

    hyperlinks = _find_hyperlinks(document, file_path)
    # hyperlink entry schema (from XML): {"id": rId, "url": str|None, "text": str|None}

    def normalize(value: Any) -> str:
        return "".join(str(value or "").lower().split())

    if check_type == "hyperlink_present":
        expected_bool = expected if isinstance(expected, bool) else str(expected).strip().lower() not in {"false", "no", "0"}
        actual = bool(hyperlinks)
        return CheckerResult(passed=actual == expected_bool, actual=actual, details={"type": check_type})

    if check_type == "hyperlink_url":
        actual_urls = [h.get("url") for h in hyperlinks if h.get("url")]
        expected_val = expected.get("contains") if isinstance(expected, dict) else expected
        if expected_val is None:
            return CheckerResult(passed=False, actual=actual_urls, details={"type": check_type, "reason": "No expected provided"})
        expected_str = str(expected_val).strip().lower()
        passed = any(expected_str in str(url).lower() for url in actual_urls)
        return CheckerResult(passed=passed, actual=actual_urls, details={"type": check_type, "expected": expected_val})

    if check_type == "hyperlink_text":
        actual_texts = [h.get("text") for h in hyperlinks if h.get("text")]
        expected_val = expected.get("contains") if isinstance(expected, dict) else expected
        if expected_val is None:
            return CheckerResult(passed=False, actual=actual_texts, details={"type": check_type, "reason": "No expected provided"})
        expected_str = normalize(expected_val)
        passed = any(expected_str in normalize(t) for t in actual_texts)
        return CheckerResult(passed=passed, actual=actual_texts, details={"type": check_type, "expected": expected_val})

    if check_type == "hyperlink_text_destination":
        if not isinstance(expected, dict):
            return CheckerResult(passed=False, details={"type": check_type, "reason": "Link text and destination are required."})
        text = normalize(expected.get("text", ""))
        destination = str(expected.get("destination", "")).strip().lower()
        passed = bool(text and destination) and any(
            text in normalize(link.get("text"))
            and destination in str(link.get("url") or "").lower()
            for link in hyperlinks
        )
        return CheckerResult(passed=passed, actual=hyperlinks, details={"type": check_type, "expected": expected})

    return CheckerResult(passed=False, details={"reason": f"Unsupported hyperlink check type: {check_type}"})


def _find_hyperlinks(document: Document, file_path: Path) -> List[Dict[str, Optional[str]]]:
    """Extract hyperlink destination and visible text.

    Notes:
    - docx's high-level API does not expose this directly.
    - We use raw XML extraction from paragraphs to keep it lightweight.
    """
    # Namespaces for hyperlink + relationships.
    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    XLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

    # For mapping r:id -> target URL, read relationships from the document package.
    rels = {}
    try:
        for rel in document.part.rels.values():
            # rel.reltype often like http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink
            if "hyperlink" in rel.reltype:
                rels[rel.rId] = rel.target_ref
    except Exception:
        rels = {}

    hyperlinks: List[Dict[str, Optional[str]]] = []

    def iter_paragraph_hyperlinks(paragraph_xml_root) -> List[Dict[str, Optional[str]]]:
        results: List[Dict[str, Optional[str]]] = []
        # hyperlink element carries r:id
        for hl in paragraph_xml_root.findall(f".//{{{WNS}}}hyperlink"):
            rid = hl.get(f"{{{WNS}}}id") or hl.get(f"{{{XLINK}}}id")
            url = rels.get(rid) if rid else None
            # gather displayed text from runs within hyperlink
            texts = []
            for t in hl.findall(f".//{{{WNS}}}t"):
                if t.text and t.text.strip():
                    texts.append(t.text.strip())
            text = " ".join(texts).strip() if texts else None
            results.append({"id": rid or "", "url": url, "text": text})
        return results

    try:
        for para in document.paragraphs:
            try:
                root = etree.fromstring(para._p.xml.encode("utf-8"))
            except Exception:
                continue
            hyperlinks.extend(iter_paragraph_hyperlinks(root))
    except Exception:
        pass

    if hyperlinks:
        return hyperlinks

    try:
        with ZipFile(file_path, "r") as zf:
            rel_xml = zf.read("word/_rels/document.xml.rels")
            doc_xml = zf.read("word/document.xml")
        rel_root = etree.fromstring(rel_xml)
        rels = {
            rel.get("Id"): rel.get("Target")
            for rel in rel_root.findall(f".//{{{PKG_REL}}}Relationship")
            if "hyperlink" in (rel.get("Type") or "")
        }
        doc_root = etree.fromstring(doc_xml)
        for hl in doc_root.findall(f".//{{{WNS}}}hyperlink"):
            rid = hl.get(f"{{{XLINK}}}id")
            texts = [node.text.strip() for node in hl.findall(f".//{{{WNS}}}t") if node.text and node.text.strip()]
            hyperlinks.append({"id": rid or "", "url": rels.get(rid), "text": " ".join(texts) or None})
    except Exception:
        pass

    return hyperlinks
