"""Convert structured_expectations.json into Marking_Experiment task JSON.

Your `structured_expectations.json` currently has this shape:
{
  "metadata": {...},
  "checks": [
     {"id":..., "question":..., "file":..., "type":..., "anchor":..., "property":..., "expected":..., "mark":...}
  ]
}

The Marking_Experiment engine expects:
{
  "task_name": ...,
  "program": "word"|"excel"|...,  (primarily for checker dispatch)
  "file": "student_file.docx" (placeholder)
  "total_marks": ...,
  "questions": [
    {"question_number":..., "description":..., "marks":..., "domain":..., "type":..., "target":{...}, "expected":...}
  ]
}

This script converts each check into one engine question.

Notes on mapping:
- `file` is informational; engine uses the learner submission file path supplied at runtime.
- We map:
    domain <- "word" or "excel" inferred from check.type prefix
    engine question.type <- <property> (engine's "check_type")
    engine question.target <- anchor (plus if anchor/value-like fields exist)
- `anchor` can be null. Engine checkers vary; we pass through as target.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _infer_program(check_type: str) -> str:
    ct = (check_type or "").lower()
    if ct.startswith("xlsx"):
        return "excel"
    if ct.startswith("docx"):
        return "word"
    if ct.startswith("html"):
        return "html"
    if ct.startswith("access"):
        return "access"
    # Fallback
    return "word"


def _infer_domain(program: str) -> str:
    # Engine uses domain names inside WordChecker: paragraph_formatting/font/table/list/object/advanced/document.
    # Your structured_expectations uses check.type prefixes like:
    #  - docx_page_setup
    #  - docx_text_spacing
    #  - docx_run_format
    #  - docx_cover_page
    # We'll map those to engine domains based on the prefix.
    return program


def _map_check_to_question(check: Dict[str, Any]) -> Dict[str, Any]:
    check_type = check.get("type")
    expected = check.get("expected")
    marks = int(check.get("mark", 1))

    program = _infer_program(str(check_type))

    # IMPORTANT: Map your structured_expectations docx_* checks onto the
    # existing Marking_Experiment WordChecker domains/check types.
    # WordChecker currently supports:
    #   domain: paragraph_formatting/font/table/list/object/advanced/document
    #   and only a subset of check_type strings under each domain.
    domain = "paragraph_formatting"
    ctt = str(check_type).lower()

    # --- Layout / page setup ---
    # These should be checked at the DOCUMENT level.
    if ctt.startswith("docx_page_setup"):
        domain = "document"
    elif ctt.startswith("docx_text_spacing"):
        domain = "paragraph_formatting"
    elif ctt.startswith("docx_paragraph_format") or ctt.startswith("docx_paragraph_structure") or ctt.startswith("docx_paragraph_style") or ctt.startswith("docx_paragraph_formatting"):
        domain = "paragraph_formatting"

    # --- Font/runs ---
    elif ctt.startswith("docx_run_format") or ctt.startswith("docx_text_content"):
        domain = "font"
    elif ctt.startswith("docx_text_count"):
        # Not implemented currently in WordChecker; leave as paragraph_formatting so we can extend next.
        domain = "paragraph_formatting"

    # --- Tables ---
    elif ctt.startswith("docx_table"):
        domain = "table"

    # --- Lists ---
    elif ctt.startswith("docx_list"):
        domain = "list"

    # --- Cover/pages (currently unsupported by WordChecker, but keep domain=document so we can implement next) ---
    elif ctt.startswith("docx_cover") or ctt.startswith("docx_cover_page") or ctt.startswith("docx_content_controls"):
        domain = "document"
    elif ctt.startswith("docx_textbox"):
        # textbox checks are typically advanced/object; keep as object for now.
        domain = "object"

    # --- Comments/headings/etc ---
    elif ctt.startswith("docx_comment"):
        domain = "advanced"
    elif ctt.startswith("docx_heading"):
        domain = "advanced"

    # --- Document metadata ---
    elif ctt.startswith("docx_document_property"):
        domain = "document"
    elif ctt.startswith("docx_page_border"):
        domain = "document"

    # --- Find/replace ---
    elif ctt.startswith("docx_find_replace"):
        domain = "paragraph_formatting"

    # --- Objects ---
    elif ctt.startswith("docx_object"):
        domain = "object"

    # engine's check_type is the property string
    engine_check_type = check.get("property")

    # anchor -> target
    anchor = check.get("anchor")
    target: Dict[str, Any] = {}
    if isinstance(anchor, dict):
        # Keep original anchor details for downstream use/debugging.
        target = dict(anchor)

        # IMPORTANT TABLE TARGETING:
        # WordChecker.find_table() only supports locator/value-based targeting:
        #   - table_index (value is int)
        #   - near_text / after_heading / contains_text (value is text)
        #
        # Your structured expectations for docx_table use keys like:
        #   after_paragraph/row/column/cell_text/rows/... which are NOT understood by find_table().
        # So we translate them into a supported locator/value pair.
        if domain == "table":
            # Current WordChecker.find_table() only supports table_index and
            # near_text/after_heading/contains_text targeting based on paragraph instances.
            # Your structured anchors for tables are paragraph-fragment-based and
            # frequently don't match the paragraph element used by python-docx,
            # causing hard failures (could not find table).
            #
            # Minimal robust fallback: always select the first table.
            target = {"locator": "table_index", "value": 0}

            # Preserve the full original anchor for later refinement.
            target["_anchor"] = dict(anchor)

    question_number = str(check.get("question"))
    description = f"{domain}.{engine_check_type}"

    return {
        "question_number": question_number,
        "description": description,
        "marks": marks,
        "domain": domain,
        "type": str(engine_check_type),
        "target": target,
        "expected": expected,
    }



def convert(structured_path: Path, out_task_path: Path) -> None:
    structured = json.loads(structured_path.read_text(encoding="utf-8"))
    checks: List[Dict[str, Any]] = structured.get("checks", [])

    questions = [_map_check_to_question(c) for c in checks]
    total_marks = sum(int(q["marks"]) for q in questions)

    # Determine overall program
    program = "word"
    if checks:
        program = _infer_program(str(checks[0].get("type", "")))

    task_name = structured.get("metadata", {}).get("name", "Converted Task")

    task = {
        "task_name": task_name,
        "program": program,
        "file": "student_file.docx" if program == "word" else "student_file.xlsx",
        "total_marks": total_marks,
        "questions": questions,
    }

    out_task_path.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    structured_path = base / "structured_expectations.json"
    out_path = base / "task_from_structured_expectations.json"
    convert(structured_path, out_path)
    print(f"Converted -> {out_path}")

