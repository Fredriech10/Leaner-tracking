"""Marks Grade 11 Term 2 practical Question 5 from one uploaded Access database."""

from __future__ import annotations

from pathlib import Path

import pythoncom

from marking.merkwerk.gr11_term2_checks import q5_checks


ROWS = (4, 7, 8, 9, 11, 13, 17, 18, 19, 20, 33, 34, 35, 38, 39, 40, 41, 46, 47, 48)


def _is_access_database(filepath: str) -> bool:
    try:
        header = Path(filepath).read_bytes()[:64]
    except OSError:
        return False
    return b"Standard Jet DB" in header or b"ACE" in header


def mark(filepath: str) -> dict:
    if not _is_access_database(filepath):
        results = [{"question": f"Question 5 marking item {row}", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in ROWS]
        return {"task_name": "CAT Grade 11 Term 2: Database Question 5", "score": 0, "total": len(ROWS), "percentage": 0, "results": results, "error": None}

    pythoncom.CoInitialize()
    try:
        outcomes = q5_checks(Path(filepath).resolve())
    except Exception as exc:
        results = [{"question": f"Question 5 marking item {row}: marker unavailable ({exc})", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in ROWS]
        return {"task_name": "CAT Grade 11 Term 2: Database Question 5", "score": 0, "total": len(ROWS), "percentage": 0, "results": results, "error": None}
    finally:
        pythoncom.CoUninitialize()

    results = []
    for (_sheet, row), outcome in sorted(outcomes.items(), key=lambda item: item[0][1]):
        passed = outcome.value == 1
        results.append({"question": f"Question 5 marking item {row}", "marks_available": 1, "marks_awarded": 1 if passed else 0, "passed": passed})
    score = sum(item["marks_awarded"] for item in results)
    return {"task_name": "CAT Grade 11 Term 2: Database Question 5", "score": score, "total": len(results), "percentage": round(score / len(results) * 100) if results else 0, "results": results, "error": None}
