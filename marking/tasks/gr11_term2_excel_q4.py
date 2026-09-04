"""Marks Grade 11 Term 2 practical Question 4 from one uploaded workbook."""

from __future__ import annotations

from pathlib import Path

import pythoncom

from marking.merkwerk.gr11_term2_checks import q4_checks
from marking.tasks._gr10_term3 import _detect_content_type


ROWS = (6, 7, 8, 11, 12, 13, 14, 15, 16)


def mark(filepath: str) -> dict:
    if _detect_content_type(filepath) != "excel":
        results = [{"question": f"Question 4 marking item {row}", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in ROWS]
        return {"task_name": "CAT Grade 11 Term 2: Spreadsheet Question 4", "score": 0, "total": len(ROWS), "percentage": 0, "results": results, "error": None}

    pythoncom.CoInitialize()
    try:
        outcomes = q4_checks(Path(filepath).resolve())
    except Exception as exc:
        results = [{"question": f"Question 4 marking item {row}: marker unavailable ({exc})", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in ROWS]
        return {"task_name": "CAT Grade 11 Term 2: Spreadsheet Question 4", "score": 0, "total": len(ROWS), "percentage": 0, "results": results, "error": None}
    finally:
        pythoncom.CoUninitialize()

    results = []
    for (_sheet, row), outcome in sorted(outcomes.items(), key=lambda item: item[0][1]):
        passed = outcome.value == 1
        results.append({"question": f"Question 4 marking item {row}", "marks_available": 1, "marks_awarded": 1 if passed else 0, "passed": passed})
    score = sum(item["marks_awarded"] for item in results)
    return {"task_name": "CAT Grade 11 Term 2: Spreadsheet Question 4", "score": score, "total": len(results), "percentage": round(score / len(results) * 100) if results else 0, "results": results, "error": None}
