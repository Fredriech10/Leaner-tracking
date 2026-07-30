"""marking_experiment_adapter.py

Adapter marking script for Flask learner tracking.

- Exposes mark(filepath) -> standard dict expected by app.py.
- Uses Marking_Experiment/structured_expectations.json to build an engine task.
- Runs Marking_Experiment.MarkingEngine against the submitted document.

This adapter is intentionally lightweight: it converts the engine session results into
Filsk's question-level result format.
"""

from __future__ import annotations

import json
import os
import sqlite3

from pathlib import Path
from typing import Any, Dict, List, Optional

from marking.base_marker import mark_task


def _project_root() -> Path:
    # marking/tasks/*.py -> marking/tasks -> marking -> repo root (Leaner tracking)
    return Path(__file__).resolve().parents[2]


def _structured_expectations_path() -> Path:
    # Based on repo layout: structured_expectations.json sits at repo root.
    return _project_root() / "structured_expectations.json"


def _marking_db_path() -> Path:
    return _project_root() / "marking_experiment.db"


def _load_structured_expectations() -> Dict[str, Any]:
    p = _structured_expectations_path()
    if not p.exists():
        raise FileNotFoundError(f"structured_expectations.json not found at: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _ensure_marking_experiment_on_path() -> None:
    # The engine is in repo root/Marking_Experiment.
    root = _project_root()
    pkg_dir = root / "Marking_Experiment"
    if not pkg_dir.exists():
        raise FileNotFoundError(f"Marking_Experiment package not found at: {pkg_dir}")

    # Make sure we can import it as a package.
    # Since Flask executes from repo root-ish, this is usually not required,
    # but adding paths is safer.
    import sys

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _run_experiment_engine(filepath: str) -> Dict[str, Any]:
    """Run Marking_Experiment engine directly and return a standardized result."""

    _ensure_marking_experiment_on_path()

    from Marking_Experiment.engine import MarkingEngine
    from Marking_Experiment.structured_expectations_to_task import convert

    root = _project_root()
    base = root

    structured = _load_structured_expectations()

    # Convert structured expectations -> task json expected by engine.
    # Use the existing converter to keep mapping consistent.
    task_path = base / "task_from_structured_expectations.json"

    # Converter writes file; we can either call convert() or build in-memory.
    convert(_structured_expectations_path(), task_path)

    task_definition = json.loads(task_path.read_text(encoding="utf-8"))
    # Engine wants a Path.
    engine = MarkingEngine()
    session = engine.run_task(task_definition, Path(filepath))

    # session.score/total_marks exist in Marking_Experiment.marking_experiment.
    # We'll map its per-check results to per-question results.
    task_name = getattr(session, "task_name", task_definition.get("task_name", "Marking Experiment"))
    total = int(getattr(session, "total_marks", task_definition.get("total_marks", 0)) or 0)
    score = int(getattr(session, "score", 0) or 0)
    percentage = round((score / total) * 100) if total else 0

    results_out: List[Dict[str, Any]] = []
    for r in getattr(session, "results", []) or []:
        qn = getattr(r, "question_number", "")
        desc = getattr(r, "description", "")
        passed = bool(getattr(r, "passed", False))
        marks_avail = int(getattr(r, "marks", 1) or 1)

        results_out.append(
            {
                "question": f"{qn} {desc}".strip(),
                "marks_available": marks_avail,
                "marks_awarded": marks_avail if passed else 0,
                "passed": passed,
            }
        )

    return {
        "task_name": task_name,
        "score": score,
        "total": total,
        "percentage": percentage,
        "results": results_out,
        "error": None,
    }


def _run_task_definition(filepath: str, task_definition: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_marking_experiment_on_path()

    from Marking_Experiment.engine import MarkingEngine

    engine = MarkingEngine()
    session = engine.run_task(task_definition, Path(filepath))

    task_name = getattr(session, "task_name", task_definition.get("task_name", "Marking Experiment"))
    total = int(getattr(session, "total_marks", task_definition.get("total_marks", 0)) or 0)
    score = int(getattr(session, "score", 0) or 0)
    percentage = round((score / total) * 100) if total else 0

    results_out: List[Dict[str, Any]] = []
    for r in getattr(session, "results", []) or []:
        qn = getattr(r, "question_number", "")
        desc = getattr(r, "description", "")
        passed = bool(getattr(r, "passed", False))
        marks_avail = int(getattr(r, "marks", 1) or 1)
        results_out.append(
            {
                "question": f"{qn} {desc}".strip(),
                "marks_available": marks_avail,
                "marks_awarded": marks_avail if passed else 0,
                "passed": passed,
            }
        )

    return {
        "task_name": task_name,
        "score": score,
        "total": total,
        "percentage": percentage,
        "results": results_out,
        "error": None,
    }


def _load_setup_task_definition(marking_setup_id: int) -> Dict[str, Any]:
    db_path = _marking_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"marking_experiment.db not found at: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT json_script_blob FROM marking_setups WHERE id = ?",
            (marking_setup_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        raise FileNotFoundError(f"No generated JSON found for marking setup id {marking_setup_id}.")

    blob = row[0]
    if isinstance(blob, bytes):
        text = blob.decode("utf-8")
    else:
        text = str(blob)
    task_definition = json.loads(text)
    if not isinstance(task_definition, dict) or "questions" not in task_definition:
        raise ValueError(f"Generated JSON for marking setup id {marking_setup_id} is not a task definition.")
    return task_definition


def mark(filepath: str) -> Dict[str, Any]:
    """Flask marking script entrypoint."""

    # This adapter targets Word submissions.
    expected_extension = ".docx"

    # Validate extension quickly and provide user-friendly errors via base_marker.
    if not filepath.lower().endswith(expected_extension):
        return {
            "task_name": "Marking Experiment",
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": f"Wrong file type submitted. Expected a Word document (.docx).",
        }

    try:
        return _run_experiment_engine(filepath)
    except FileNotFoundError as e:
        return {
            "task_name": "Marking Experiment",
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": str(e),
        }
    except Exception as e:
        return {
            "task_name": "Marking Experiment",
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": f"Marking experiment failed: {e}",
        }


def mark_with_setup(filepath: str, marking_setup_id: int) -> Dict[str, Any]:
    expected_extension = ".docx"
    if not filepath.lower().endswith(expected_extension):
        return {
            "task_name": "Marking Experiment",
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": "Wrong file type submitted. Expected a Word document (.docx).",
        }

    try:
        task_definition = _load_setup_task_definition(int(marking_setup_id))
        return _run_task_definition(filepath, task_definition)
    except Exception as e:
        return {
            "task_name": "Marking Experiment",
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": f"Marking setup failed: {e}",
        }

