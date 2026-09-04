"""Marks Grade 11 Term 2 practical Question 6 from one uploaded HTML file."""

from __future__ import annotations

from pathlib import Path

from marking.merkwerk.gr11_term2_checks import q6_checks
from marking.tasks._gr10_term3 import _detect_content_type


ROWS = (3, 6, 7, 10, 11, 12, 15, 16, 19, 20, 21, 22, 24, 26, 29)


def mark(filepath: str) -> dict:
    if _detect_content_type(filepath) != "html":
        results = [{"question": f"Question 6 marking item {row}", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in ROWS]
        return {"task_name": "CAT Grade 11 Term 2: HTML Question 6", "score": 0, "total": len(ROWS), "percentage": 0, "results": results, "error": None}
    outcomes = q6_checks(Path(filepath)); results = []
    for (_sheet, row), outcome in sorted(outcomes.items(), key=lambda item: item[0][1]):
        passed = outcome.value == 1
        results.append({"question": f"Question 6 marking item {row}", "marks_available": 1, "marks_awarded": 1 if passed else 0, "passed": passed})
    score = sum(item["marks_awarded"] for item in results)
    return {"task_name": "CAT Grade 11 Term 2: HTML Question 6", "score": score, "total": len(results), "percentage": round(score / len(results) * 100) if results else 0, "results": results, "error": None}
