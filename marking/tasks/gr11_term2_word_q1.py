"""Marks Grade 11 Term 2 practical Question 1 from one uploaded DOCX."""

from __future__ import annotations

from pathlib import Path

from marking.merkwerk.gr11_term2_checks import q1_checks
from marking.tasks._gr10_term3 import _detect_content_type


def mark(filepath: str) -> dict:
    if _detect_content_type(filepath) != "word":
        results = [{"question": f"Question 1 row {row}", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in (4, 5, 6, 8, 9, 10, 14, 15, 16, 17, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29)]
        return {"task_name": "CAT Grade 11 Term 2: Word Question 1", "score": 0, "total": 20, "percentage": 0, "results": results, "error": None}
    outcomes = q1_checks(Path(filepath))
    results = []
    for (_sheet, row), outcome in sorted(outcomes.items(), key=lambda item: item[0][1]):
        passed = outcome.value == 1
        results.append({"question": f"Question 1 marking item {row}", "marks_available": 1, "marks_awarded": 1 if passed else 0, "passed": passed})
    score = sum(item["marks_awarded"] for item in results)
    return {"task_name": "CAT Grade 11 Term 2: Word Question 1", "score": score, "total": len(results), "percentage": round(score / len(results) * 100) if results else 0, "results": results, "error": None}
