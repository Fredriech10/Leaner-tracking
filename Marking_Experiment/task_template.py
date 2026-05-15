"""Template utilities for Marking Experiment task definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def build_question_template(
    question_number: str,
    description: str,
    domain: str,
    check_type: str,
    target_locator: str,
    target_value: Any,
    expected: Any,
    marks: int = 1,
) -> Dict[str, Any]:
    return {
        "question_number": question_number,
        "description": description,
        "marks": marks,
        "domain": domain,
        "type": check_type,
        "target": {"locator": target_locator, "value": target_value},
        "expected": expected,
    }


def build_task_template(
    task_name: str = "New Experimental Task",
    program: str = "word",
    questions: Optional[List[Dict[str, Any]]] = None,
    total_marks: Optional[int] = None,
) -> Dict[str, Any]:
    if questions is None:
        questions = [
            build_question_template(
                "1",
                "Example check description.",
                "paragraph_formatting",
                "alignment",
                "after_heading",
                "Introduction",
                "justify",
                1,
            )
        ]
    if total_marks is None:
        total_marks = sum(int(question.get("marks", 1)) for question in questions)
    return {
        "task_name": task_name,
        "program": program,
        "file": "student_file.docx" if program == "word" else "student_file.xlsx",
        "total_marks": total_marks,
        "questions": questions,
    }


def save_task_template(path: Path, template: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as target:
        json.dump(template, target, indent=2, ensure_ascii=False)
