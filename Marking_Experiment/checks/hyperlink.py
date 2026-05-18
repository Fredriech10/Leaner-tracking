"""Hyperlink rule checker for Word documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document

from ..checker_types import CheckerResult


def check_hyperlink_rule(rule: Dict[str, Any], file_path: Path) -> CheckerResult:
    document = Document(file_path)
    check_type = str(rule.get("type", ""))
    expected = rule.get("expected")

    hyperlinks = _find_hyperlinks(document)
    # hyperlink entry schema (from XML): {"id": rId, "url": str|None, "text": str|None}

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
        expected_str = str(expected_val).strip().lower()
        passed = any(expected_str in str(t).lower() for t in actual_texts)
        return CheckerResult(passed=passed, actual=actual_texts, details={"type": check_type, "expected": expected_val})

    return CheckerResult(passed=False, details={"reason": f"Unsupported hyperlink check type: {check_type}"})


def _find_hyperlinks(document: Document) -> List[Dict[str, Optional[str]]]:
    """Extract hyperlink destination and visible text.

    Notes:
    - docx's high-level API does not expose this directly.
    - We use raw XML extraction from paragraphs to keep it lightweight.
    """
    from lxml import etree

    # Namespaces for hyperlink + relationships.
    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    XLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

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

    return hyperlinks

