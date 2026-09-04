"""Marks Grade 12 Term 2 practical Question 1 from one uploaded DOCX."""

from __future__ import annotations

import json
from pathlib import Path

from marking.merkwerk.gr12_term2_q1 import Q1Document, evaluate_q1_check
from marking.tasks._gr10_term3 import _detect_content_type


EXPECTATIONS_PATH = Path(__file__).resolve().parent.parent / "merkwerk" / "gr12_term2_expectations.json"


def _checks() -> list[dict]:
    data = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
    question = next(item for item in data["questions"] if item["sheet"] == "Q1")
    return [check for check in question["checks"] if check.get("is_scoring")]


def mark(filepath: str) -> dict:
    checks = _checks()
    if _detect_content_type(filepath) != "word":
        results = [{"question": check["check_id"], "marks_available": check["mark"], "marks_awarded": 0, "passed": False} for check in checks]
        return {"task_name": "CAT Grade 12 Term 2: Word Question 1", "score": 0, "total": sum(c["mark"] for c in checks), "percentage": 0, "results": results, "error": None}

    document = Q1Document(Path(filepath))
    results = []
    score = 0
    total = 0
    for check in checks:
        evaluated = evaluate_q1_check(document, check)
        marks = check["mark"]
        passed = evaluated.status == "pass"
        total += marks
        score += marks if passed else 0
        results.append({
            "question": f"{check['check_id']}: {check['description']} ({evaluated.reason})",
            "marks_available": marks,
            "marks_awarded": marks if passed else 0,
            "passed": passed,
        })
    return {"task_name": "CAT Grade 12 Term 2: Word Question 1", "score": score, "total": total, "percentage": round(score / total * 100) if total else 0, "results": results, "error": None}
