"""Adapts the original Grade 10 Term 2 test marker to single-file uploads."""

from __future__ import annotations

from pathlib import Path

import pythoncom

from marking.merkwerk.gr10_term2_test_checks import AutoMarker, WordReader
from marking.tasks._gr10_term3 import _detect_content_type


TASKS = {
    1: ("Word", "check_newsletter", (3, 5, 6, 8, 9, 12, 13, 14, 15, 17, 22, 24, 26, 28, 29)),
    2: ("Word", "check_venue", (3, 5, 7, 8, 9, 11, 12, 13, 14, 17, 18, 19, 20)),
    3: ("Spreadsheet", "check_wildfires", (2, 3, 4, 6, 8, 10, 11, 13, 14, 16, 17, 19, 20, 22, 23, 24, 25)),
    4: ("Word", "check_learners", (3, 5, 7, 8)),
}


def mark_question(filepath: str, question_number: int) -> dict:
    application, method_name, rows = TASKS[question_number]
    expected_type = "excel" if application == "Spreadsheet" else "word"
    task_name = f"CAT Grade 10 Term 2 Test: {application} Question {question_number}"

    if _detect_content_type(filepath) != expected_type:
        results = [{"question": f"Question {question_number} marking item {row}", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in rows]
        return {"task_name": task_name, "score": 0, "total": len(rows), "percentage": 0, "results": results, "error": None}

    pythoncom.CoInitialize()
    reader = None
    try:
        if application == "Word":
            reader = WordReader()
        marker = AutoMarker("learner", Path(filepath).resolve().parent, reader)
        marks = getattr(marker, method_name)(Path(filepath).resolve())
    except Exception as exc:
        results = [{"question": f"Question {question_number} marking item {row}: marker unavailable ({exc})", "marks_available": 1, "marks_awarded": 0, "passed": False} for row in rows]
        return {"task_name": task_name, "score": 0, "total": len(rows), "percentage": 0, "results": results, "error": None}
    finally:
        if reader is not None:
            reader.close()
        pythoncom.CoUninitialize()

    results = [
        {"question": f"Question {question_number} marking item {row}", "marks_available": 1, "marks_awarded": 1 if value else 0, "passed": bool(value)}
        for row, value in sorted(marks.items())
    ]
    score = sum(item["marks_awarded"] for item in results)
    return {"task_name": task_name, "score": score, "total": len(results), "percentage": round(score / len(results) * 100) if results else 0, "results": results, "error": None}
