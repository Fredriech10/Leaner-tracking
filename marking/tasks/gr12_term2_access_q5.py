"""Marks Grade 12 Term 2 practical Question 5 from one uploaded Access database."""

from __future__ import annotations

import json
from pathlib import Path

from marking.merkwerk.gr12_term2_q5 import Q5Database, evaluate_q5_check

EXPECTATIONS_PATH = Path(__file__).resolve().parent.parent / "merkwerk" / "gr12_term2_expectations.json"


def _checks() -> list[dict]:
    data = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
    question = next(item for item in data["questions"] if item["sheet"] == "Q5")
    return [check for check in question["checks"] if check.get("is_scoring")]


def _is_access_database(filepath: str) -> bool:
    try:
        header = Path(filepath).read_bytes()[:64]
    except OSError:
        return False
    return b"Standard Jet DB" in header or b"ACE" in header


def mark(filepath: str) -> dict:
    checks = _checks()
    if not _is_access_database(filepath):
        results = [{"question": c["check_id"], "marks_available": c["mark"], "marks_awarded": 0, "passed": False} for c in checks]
        return {"task_name": "CAT Grade 12 Term 2: Database Question 5", "score": 0, "total": sum(c["mark"] for c in checks), "percentage": 0, "results": results, "error": None}
    database = Q5Database(Path(filepath))
    results, score, total = [], 0, 0
    for check in checks:
        outcome = evaluate_q5_check(database, check); marks = check["mark"]; passed = outcome.status == "pass"
        total += marks; score += marks if passed else 0
        results.append({"question": f"{check['check_id']}: {check['description']} ({outcome.reason})", "marks_available": marks, "marks_awarded": marks if passed else 0, "passed": passed})
    return {"task_name": "CAT Grade 12 Term 2: Database Question 5", "score": score, "total": total, "percentage": round(score / total * 100) if total else 0, "results": results, "error": None}
