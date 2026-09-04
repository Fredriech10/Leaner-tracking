"""Adapts the Grade 11 Term 3 Task 4 marker to individual uploads."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pythoncom

from marking.merkwerk.gr11_term3_checks import AccessMarker, ExcelMarker, HtmlMarker, WordMarker
from marking.tasks._gr10_term3 import _detect_content_type


TASKS = {
    1: ("Word", "word", WordMarker),
    2: ("Spreadsheet", "excel", ExcelMarker),
    3: ("Database", "access", AccessMarker),
    4: ("Web Design", "html", HtmlMarker),
}


def _is_access_database(filepath: str) -> bool:
    try:
        header = Path(filepath).read_bytes()[:64]
    except OSError:
        return False
    return b"Standard Jet DB" in header or b"ACE" in header


def _results_for_tracking(mark_results) -> tuple[list[dict], int, int]:
    results = []
    for result in mark_results:
        results.append(
            {
                "question": f"{result.item}: {result.description}",
                "marks_available": result.max_mark,
                "marks_awarded": result.mark_awarded,
                "passed": result.passed,
            }
        )
    score = sum(item["marks_awarded"] for item in results)
    total = sum(item["marks_available"] for item in results)
    return results, score, total


def mark_question(filepath: str, question_number: int) -> dict:
    application, expected_type, marker_class = TASKS[question_number]
    task_name = f"CAT Grade 11 Term 3 Task 4: {application} Question {question_number}"
    valid = _is_access_database(filepath) if expected_type == "access" else _detect_content_type(filepath) == expected_type
    if not valid:
        return {
            "task_name": task_name,
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": f"Wrong file type submitted for Question {question_number}.",
        }

    absolute_path = Path(filepath).resolve()
    pythoncom.CoInitialize()
    try:
        if question_number == 2:
            mark_results = marker_class(absolute_path, absolute_path.parent).mark()
            # The original final two marks require a separate PDF upload. This
            # application accepts one upload, so only workbook settings are scored.
            print_result = mark_results[-1]
            workbook_marks = sum(token in print_result.evidence for token in (
                "print_area_ok=True",
                "title_rows_ok=True",
                "landscape_ok=True",
                "fit_columns_ok=True",
            ))
            mark_results[-1] = replace(
                print_result,
                max_mark=4,
                mark_awarded=workbook_marks,
                passed=workbook_marks == 4,
                description="Print setup configured in the workbook",
            )
        else:
            mark_results = marker_class(absolute_path).mark()
    except Exception as exc:
        return {"task_name": task_name, "score": 0, "total": 0, "percentage": 0, "results": [], "error": f"Marker unavailable: {exc}"}
    finally:
        pythoncom.CoUninitialize()

    results, score, total = _results_for_tracking(mark_results)
    return {"task_name": task_name, "score": score, "total": total, "percentage": round(score / total * 100) if total else 0, "results": results, "error": None}
