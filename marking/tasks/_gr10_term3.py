"""Single-file adapters for the Grade 10 Term 3 CAT Task 4 markers."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from marking.merkwerk import gr10_term3_checks


RULES_PATH = Path(__file__).resolve().parent.parent / "merkwerk" / "gr10_term3_rules.json"


def _load_rules() -> dict:
    with RULES_PATH.open(encoding="utf-8") as rules_file:
        return json.load(rules_file)


def _detect_content_type(filepath: str) -> str | None:
    """Identify the uploaded content without relying on its submitted filename."""
    path = Path(filepath)
    try:
        with ZipFile(path) as archive:
            content_types = archive.read("[Content_Types].xml").decode("utf-8", errors="ignore").lower()
        if "wordprocessingml.document" in content_types:
            return "word"
        if "spreadsheetml.sheet" in content_types:
            return "excel"
    except (BadZipFile, KeyError, OSError):
        pass

    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lstrip().lower()
    except OSError:
        return None
    return "html" if "<html" in text or "<!doctype html" in text else None


def _wrong_file_result(task_name: str, rubric: list[dict], expected_type: str) -> dict:
    results = [
        {
            "question": f"{item['question']}: {item['criterion']}",
            "marks_available": item["marks"],
            "marks_awarded": 0,
            "passed": False,
        }
        for item in rubric
    ]
    total = sum(item["marks"] for item in rubric)
    return {
        "task_name": task_name,
        "score": 0,
        "total": total,
        "percentage": 0,
        "results": results,
        # This remains a normal, recorded attempt so an invalid upload receives 0.
        "error": None,
    }


def mark_submission(filepath: str, content_type: str, task_name: str) -> dict:
    rules = _load_rules()
    rubric = rules[f"{content_type}_checks"]
    if _detect_content_type(filepath) != content_type:
        return _wrong_file_result(task_name, rubric, content_type.upper())

    file_path = Path(filepath)
    learner_folder = file_path.parent
    learner_name = "Learner upload"
    if content_type == "word":
        rows = gr10_term3_checks.check_word_doc(learner_name, learner_folder, file_path, rules)
    elif content_type == "excel":
        rows = gr10_term3_checks.check_excel_book(learner_name, learner_folder, file_path, rules)
    else:
        rows = gr10_term3_checks.check_html_page(learner_name, learner_folder, file_path, None, rules)

    results = []
    score = 0.0
    total = 0.0
    for row in rows:
        maximum = float(row.get("maximum_mark") or 0)
        if maximum <= 0:
            continue
        awarded = row.get("awarded_mark")
        numeric_awarded = float(awarded) if isinstance(awarded, (int, float)) else 0.0
        passed = numeric_awarded >= maximum
        total += maximum
        score += min(max(numeric_awarded, 0.0), maximum)
        results.append(
            {
                "question": f"{row['question']}: {row['criterion']}",
                "marks_available": int(maximum) if maximum.is_integer() else maximum,
                "marks_awarded": int(numeric_awarded) if numeric_awarded.is_integer() else numeric_awarded,
                "passed": passed,
            }
        )

    score_value = int(score) if score.is_integer() else score
    total_value = int(total) if total.is_integer() else total
    return {
        "task_name": task_name,
        "score": score_value,
        "total": total_value,
        "percentage": round((score / total) * 100) if total else 0,
        "results": results,
        "error": None,
    }
