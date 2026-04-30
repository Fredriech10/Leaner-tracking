"""
base_marker.py
Handles file validation, running all question checks, scoring and
returning a standard result dict that Flask can use directly.
"""

import os

ALLOWED_EXTENSIONS = {
    ".xlsx": "Excel spreadsheet (.xlsx)",
    ".docx": "Word document (.docx)",
    ".accdb": "Access database (.accdb)",
    ".html": "HTML file (.html)",
}


def mark_task(filepath, expected_extension, task_name, questions):
    """
    Run all checks for a task and return a standardised result dict.

    Parameters
    ----------
    filepath : str
        Path to the submitted file.
    expected_extension : str
        Expected file extension e.g. '.xlsx'
    task_name : str
        Human-readable task name shown to the learner.
    questions : list[dict]
        Each dict must have:
            'question'  : str   - description shown to learner
            'marks'     : int   - marks awarded if correct
            'check'     : callable - checker function to call
            'params'    : dict  - keyword arguments passed to checker

    Returns
    -------
    dict with keys:
        task_name, score, total, percentage,
        results (list of per-question dicts), error
    """

    # ── File existence check ──────────────────────────────────────────
    if not os.path.exists(filepath):
        return _error_result(task_name, "Submitted file was not found on the server.")

    # ── File type check ───────────────────────────────────────────────
    _, ext = os.path.splitext(filepath)
    ext = ext.lower()

    if ext != expected_extension.lower():
        expected_label = ALLOWED_EXTENSIONS.get(expected_extension, expected_extension)
        return _error_result(
            task_name,
            f"Wrong file type submitted. Expected a {expected_label} but received '{ext}'."
        )

    # ── Run all question checks ───────────────────────────────────────
    results = []
    score = 0
    total = 0

    for q in questions:
        question_text = q.get("question", "Unnamed question")
        marks = q.get("marks", 1)
        check_fn = q.get("check")
        params = q.get("params", {})

        total += marks

        try:
            passed = check_fn(filepath, **params)
        except Exception as e:
            passed = False
            question_text = f"{question_text} [check error: {e}]"

        if passed:
            score += marks

        results.append({
            "question": question_text,
            "marks_available": marks,
            "marks_awarded": marks if passed else 0,
            "passed": passed,
        })

    percentage = round((score / total) * 100) if total else 0

    return {
        "task_name": task_name,
        "score": score,
        "total": total,
        "percentage": percentage,
        "results": results,
        "error": None,
    }


def _error_result(task_name, message):
    """Return a result dict representing a file-level error."""
    return {
        "task_name": task_name,
        "score": 0,
        "total": 0,
        "percentage": 0,
        "results": [],
        "error": message,
    }
