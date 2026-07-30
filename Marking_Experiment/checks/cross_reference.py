"""Cross-reference rule checker for Word documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from docx import Document

from ..checker_types import CheckerResult


def check_cross_reference_rule(rule: Dict[str, Any], file_path: Path) -> CheckerResult:
    document = Document(file_path)
    check_type = str(rule.get("type", ""))
    expected = rule.get("expected")

    bookmarks = _find_bookmarks(file_path)
    # bookmarks: set of bookmark names

    if check_type == "cross_reference_target":
        expected_val = expected.get("target_bookmark") if isinstance(expected, dict) else expected
        if expected_val is None:
            return CheckerResult(passed=False, actual={"bookmarks": list(bookmarks)}, details={"type": check_type, "reason": "No expected provided"})

        expected_str = str(expected_val).strip().lower()
        # We treat a target match as: any cross-reference's result points to a bookmark
        # AND that bookmark exists in the document.
        referenced = _find_cross_reference_targets(file_path)
        passed = (expected_str in referenced) and any(expected_str == b.lower() for b in bookmarks)
        return CheckerResult(passed=passed, actual={"referenced_targets": sorted(referenced), "bookmarks": sorted(bookmarks)}, details={"type": check_type, "expected": expected_val})

    if check_type == "cross_reference":
        # expected can be bool or a bookmark name substring
        expected_bool = expected if isinstance(expected, bool) else None
        referenced = _find_cross_reference_targets(file_path)
        if expected_bool is not None:
            passed = len(referenced) > 0 if expected_bool else len(referenced) == 0
            return CheckerResult(passed=passed, actual=len(referenced), details={"type": check_type})

        expected_val = expected.get("target_bookmark") if isinstance(expected, dict) else expected
        if expected_val is None:
            passed = len(referenced) > 0
            return CheckerResult(passed=passed, actual=len(referenced), details={"type": check_type})

        expected_str = str(expected_val).strip().lower()
        passed = any(expected_str in t for t in referenced)
        return CheckerResult(passed=passed, actual=sorted(referenced), details={"type": check_type, "expected": expected_val})

    return CheckerResult(passed=False, details={"reason": f"Unsupported cross-reference check type: {check_type}"})


def _find_bookmarks(file_path: Path) -> Set[str]:
    from lxml import etree
    from zipfile import ZipFile

    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    try:
        with ZipFile(file_path, "r") as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        root = etree.fromstring(xml.encode("utf-8"))
        nodes = root.findall(f".//{{{WNS}}}bookmarkStart")
        names = {n.get(f"{{{WNS}}}name") for n in nodes if n.get(f"{{{WNS}}}name")}
        return set(names)
    except Exception:
        return set()


def _find_cross_reference_targets(file_path: Path) -> Set[str]:
    """Extract bookmark targets referenced by REF fields.

    Strategy:
    - Parse document.xml.
    - Find field instructions (w:instrText) containing ' REF ' patterns.
    - Extract the bookmark name after 'REF ' and before trailing switches.

    Note: This is heuristic but works for typical REF fields like:
      { REF MyBookmark \h }
    """
    from lxml import etree

    from zipfile import ZipFile

    WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    try:
        with ZipFile(file_path, "r") as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        root = etree.fromstring(xml.encode("utf-8"))
    except Exception:
        return set()

    targets: Set[str] = set()

    # Collect instrText contents for fields.
    for instr in root.findall(f".//{{{WNS}}}instrText"):
        if instr is None or not instr.text:
            continue
        text = instr.text
        if "ref" not in text.lower():
            continue

        # Normalize whitespace for easier parsing.
        t = " ".join(text.replace("\t", " ").split())
        # Common patterns:
        #   REF MyBookmark
        #   REF  MyBookmark  \h
        # Capture token after REF.
        import re

        m = re.search(r"\bREF\b\s+([^\\\s]+)", t, flags=re.IGNORECASE)
        if m:
            targets.add(m.group(1).strip().strip('"').lower())

    # Sometimes instr is split across multiple nodes; heuristic doesn't handle all.
    return targets

