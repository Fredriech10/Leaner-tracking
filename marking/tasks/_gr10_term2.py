"""Single-file adapters for the Grade 10 Term 2 CAT practical exam."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from marking.merkwerk import gr10_term2_checks
from marking.tasks._gr10_term3 import _detect_content_type


EXPECTATIONS_PATH = Path(__file__).resolve().parent.parent / "merkwerk" / "gr10_term2_expectations.json"


def _checks_for(source_file: str) -> list[dict[str, Any]]:
    data = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
    return [check for check in data["checks"] if check["file"] == source_file]


def mark_submission(filepath: str, source_file: str, content_type: str, task_name: str) -> dict:
    checks = _checks_for(source_file)
    if _detect_content_type(filepath) != content_type:
        results = [
            {"question": check["id"], "marks_available": check.get("mark", 1), "marks_awarded": 0, "passed": False}
            for check in checks
        ]
        total = sum(check.get("mark", 1) for check in checks)
        return {"task_name": task_name, "score": 0, "total": total, "percentage": 0, "results": results, "error": None}

    path = Path(filepath)
    workbook_cache: dict[tuple[Path, bool], Any] = {}
    reader = gr10_term2_checks.DocxReader(path) if content_type == "word" else None
    results = []
    score = 0
    total = 0
    for check in checks:
        if content_type == "word":
            status, evidence = gr10_term2_checks.docx_check(reader, check)
        else:
            status, evidence = gr10_term2_checks.xlsx_check(workbook_cache, path, check)
        marks = int(check.get("mark", 1))
        passed = status == "pass"
        total += marks
        score += marks if passed else 0
        results.append(
            {
                "question": f"{check['id']}: {check['property']} ({evidence})",
                "marks_available": marks,
                "marks_awarded": marks if passed else 0,
                "passed": passed,
            }
        )
    return {
        "task_name": task_name,
        "score": score,
        "total": total,
        "percentage": round((score / total) * 100) if total else 0,
        "results": results,
        "error": None,
    }
