"""Marks the final Grade 12 Term 2 mail-merge document from one DOCX upload."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from marking.merkwerk.gr12_term2_q7 import Q7Document, evaluate_q7_check
from marking.tasks._gr10_term3 import _detect_content_type

ROOT = Path(__file__).resolve().parent.parent.parent
EXPECTATIONS_PATH = ROOT / "marking" / "merkwerk" / "gr12_term2_expectations.json"
CLIENT_LIST_PATH = ROOT / "task_samples" / "merkwerk" / "gr12_term2" / "7Client List.xlsx"


def _checks() -> list[dict]:
    data = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
    question = next(item for item in data["questions"] if item["sheet"] == "Q7")
    return [check for check in question["checks"] if check.get("is_scoring")]


def mark(filepath: str) -> dict:
    checks = _checks()
    if _detect_content_type(filepath) != "word":
        results = [{"question": c["check_id"], "marks_available": c["mark"], "marks_awarded": 0, "passed": False} for c in checks]
        return {"task_name": "CAT Grade 12 Term 2: Mail Merge Question 7", "score": 0, "total": sum(c["mark"] for c in checks), "percentage": 0, "results": results, "error": None}

    with tempfile.TemporaryDirectory(prefix="q7_mark_") as directory:
        workspace = Path(directory)
        # The learner submits one final document; the server supplies the reference client list.
        shutil.copy2(filepath, workspace / "7Marketing Letter.docx")
        shutil.copy2(filepath, workspace / "7Merged_Letters.docx")
        shutil.copy2(CLIENT_LIST_PATH, workspace / "7Client List.xlsx")
        document = Q7Document(workspace)
        results, score, total = [], 0, 0
        for check in checks:
            outcome = evaluate_q7_check(document, check); marks = check["mark"]
            passed = outcome.status == "pass"
            total += marks; score += marks if passed else 0
            results.append({"question": f"{check['check_id']}: {check['description']} ({outcome.reason})", "marks_available": marks, "marks_awarded": marks if passed else 0, "passed": passed})
    return {"task_name": "CAT Grade 12 Term 2: Mail Merge Question 7", "score": score, "total": total, "percentage": round(score / total * 100) if total else 0, "results": results, "error": None}
