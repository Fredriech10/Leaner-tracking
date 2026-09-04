"""Marks Grade 11 Term 2 practical Question 3 from one uploaded workbook."""

from __future__ import annotations

from pathlib import Path

import pythoncom

from marking.merkwerk.gr11_term2_checks import q3_checks
from marking.tasks._gr10_term3 import _detect_content_type


ROWS = (4, 6, 8, 12, 13, 14, 17, 18, 19, 20, 21, 24, 25, 26, 29, 30, 31, 32, 36, 42, 43, 44, 47, 48, 50, 51)


def mark(filepath: str) -> dict:
    if _detect_content_type(filepath) != "excel":
        results = [{"question": f"Question 3 marking item {row}", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in ROWS]
        return {"task_name": "CAT Grade 11 Term 2: Spreadsheet Question 3", "score": 0, "total": len(ROWS), "percentage": 0, "results": results, "error": None}
    pythoncom.CoInitialize()
    try:
        outcomes = q3_checks(Path(filepath).resolve())
    except Exception as exc:
        results = [{"question": f"Question 3 marking item {row}: marker unavailable ({exc})", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in ROWS]
        return {"task_name": "CAT Grade 11 Term 2: Spreadsheet Question 3", "score": 0, "total": len(ROWS), "percentage": 0, "results": results, "error": None}
    finally:
        pythoncom.CoUninitialize()
    results = []
    for (_sheet, row), outcome in sorted(outcomes.items(), key=lambda item: item[0][1]):
        passed = outcome.value == 1
        results.append({"question": f"Question 3 marking item {row}", "marks_available": 1, "marks_awarded": 1 if passed else 0, "passed": passed})
    score = sum(item["marks_awarded"] for item in results)
    return {"task_name": "CAT Grade 11 Term 2: Spreadsheet Question 3", "score": score, "total": len(results), "percentage": round(score / len(results) * 100) if results else 0, "results": results, "error": None}
