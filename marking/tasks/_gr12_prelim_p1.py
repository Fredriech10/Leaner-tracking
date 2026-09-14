"""Portal adapters for the WCED CAT Grade 12 Prelim 2026 P1 marker."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(r"E:\RTT melkies\Merk werk 2026\MErk werk\TERM 3\GR12 PRELIM P1")
SOURCE_DATA = SOURCE_ROOT / "Original Learner DATA"
MEMO_PATH = SOURCE_ROOT / "GR12 Marksheet Prelim Adjusted.xlsx"
AUTO_MARKER_PATH = SOURCE_ROOT / "auto_marker.py"


@dataclass(frozen=True)
class PortalLearner:
    name: str
    folder: Path
    files: dict[str, list[Path]]


QUESTION_CONFIG = {
    "1": {
        "task_name": "CAT Gr12 Prelim P1 - Word Question 1",
        "primary_file": "1CareerDecisions.docx",
        "rule_question": "1",
        "content_type": "word",
        "support_files": ["1Careers24.png"],
    },
    "2": {
        "task_name": "CAT Gr12 Prelim P1 - Word Question 2",
        "primary_file": "2OnlineJobs.docx",
        "rule_question": "2",
        "content_type": "word",
        "support_files": ["2WorkFromHome.png"],
    },
    "3": {
        "task_name": "CAT Gr12 Prelim P1 - Spreadsheet Question 3",
        "primary_file": "3Careers.xlsx",
        "rule_question": "3",
        "content_type": "excel",
        "support_files": [],
    },
    "4": {
        "task_name": "CAT Gr12 Prelim P1 - Spreadsheet Question 4",
        "primary_file": "4Employment.xlsx",
        "rule_question": "4",
        "content_type": "excel",
        "support_files": ["4Bachelors.png"],
    },
    "5": {
        "task_name": "CAT Gr12 Prelim P1 - Database Question 5",
        "primary_file": "5Opportunities.accdb",
        "rule_question": "5",
        "content_type": "access",
        "support_files": ["5Study.png"],
    },
    "6.1": {
        "task_name": "CAT Gr12 Prelim P1 - HTML Question 6.1",
        "primary_file": "6_1eCareers.html",
        "rule_question": "6",
        "content_type": "html",
        "support_files": ["6_1Grad.png"],
    },
    "6.2": {
        "task_name": "CAT Gr12 Prelim P1 - HTML Question 6.2",
        "primary_file": "6_2CourseFees.html",
        "rule_question": "6",
        "content_type": "html",
        "support_files": ["6_2FinPlan.png"],
    },
}


def _load_external_marker() -> Any:
    if not AUTO_MARKER_PATH.exists():
        raise FileNotFoundError(f"Prelim marker not found: {AUTO_MARKER_PATH}")
    source_root = str(SOURCE_ROOT)
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    spec = importlib.util.spec_from_file_location("gr12_prelim_p1_external_marker", AUTO_MARKER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load marker module from {AUTO_MARKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_if_exists(filename: str, target_dir: Path) -> None:
    source = SOURCE_DATA / filename
    if source.exists():
        shutil.copy2(source, target_dir / filename)


def _index_folder(folder: Path) -> dict[str, list[Path]]:
    files: dict[str, list[Path]] = {}
    for item in folder.iterdir():
        if item.is_file() and not item.name.startswith("~$"):
            files.setdefault(item.name.lower(), []).append(item)
    return files


def _result_for_wrong_file(task_name: str, rules: list[dict[str, Any]], expected_file: str) -> dict[str, Any]:
    results = []
    total = 0.0
    for rule in rules:
        marks = float(rule.get("max_mark", 0) or 0)
        if marks <= 0:
            continue
        total += marks
        results.append(
            {
                "question": f"{rule.get('question', '')}: {rule.get('criterion', '')}",
                "marks_available": int(marks) if marks.is_integer() else marks,
                "marks_awarded": 0,
                "passed": False,
            }
        )
    return {
        "task_name": task_name,
        "score": 0,
        "total": int(total) if total.is_integer() else total,
        "percentage": 0,
        "results": results,
        "error": f"Wrong file type submitted. Upload {expected_file}.",
    }


def mark_question(filepath: str, question_key: str, learner_name: str | None = None) -> dict[str, Any]:
    marker = _load_external_marker()
    config = QUESTION_CONFIG[question_key]
    task_name = config["task_name"]
    primary_file = config["primary_file"]
    rule_question = config.get("rule_question", question_key)
    upload_path = Path(filepath)

    all_rules = marker.build_rules_from_memo(MEMO_PATH)
    rules = [
        dict(rule)
        for rule in all_rules
        if str(rule.get("question", "")) == rule_question
        and (config["content_type"] == "zip" or str(rule.get("file", "")).lower() == primary_file.lower())
    ]
    for rule in rules:
        rule["_use_com"] = True
        if rule.get("file"):
            rule["_source_file"] = str(SOURCE_DATA / str(rule["file"]))

    if not rules:
        return {
            "task_name": task_name,
            "score": 0,
            "total": 0,
            "percentage": 0,
            "results": [],
            "error": f"No rules found for {task_name}.",
        }

    if upload_path.suffix.lower() != Path(primary_file).suffix.lower():
        return _result_for_wrong_file(task_name, rules, primary_file)

    with tempfile.TemporaryDirectory(prefix="gr12_prelim_p1_") as temp_name:
        temp_dir = Path(temp_name)
        if config["content_type"] == "zip":
            import zipfile

            with zipfile.ZipFile(upload_path) as archive:
                archive.extractall(temp_dir)
            files = _index_folder(temp_dir)
        else:
            learner_file = temp_dir / primary_file
            shutil.copy2(upload_path, learner_file)
            for support_file in config.get("support_files", []):
                _copy_if_exists(support_file, temp_dir)
            files = {primary_file.lower(): [learner_file]}
        learner = PortalLearner(learner_name or "Learner upload", temp_dir, files)
        specific_marker = marker.PrelimP1MarkerContext(use_com=True)

        rows = []
        for rule in rules:
            specific_row = specific_marker.check(learner, rule)
            if specific_row is not None:
                rows.append(specific_row)
                continue
            checker = marker.CHECKS.get(rule.get("type", "manual"))
            if checker is None:
                rows.append(
                    marker.ResultRow(
                        learner.name,
                        str(learner.folder),
                        str(rule.get("question", "")),
                        str(rule.get("criterion", "")),
                        float(rule.get("max_mark", 0)),
                        "MANUAL REVIEW REQUIRED",
                        "MANUAL REVIEW REQUIRED",
                        f"unknown check type: {rule.get('type')}",
                        "",
                    )
                )
                continue
            rows.append(checker(learner, rule))

    results = []
    score = 0.0
    total = 0.0
    for row in rows:
        maximum = float(row.max_mark or 0)
        if maximum <= 0:
            continue
        awarded = row.awarded_mark
        numeric_awarded = float(awarded) if isinstance(awarded, (int, float)) else 0.0
        total += maximum
        score += min(max(numeric_awarded, 0.0), maximum)
        evidence = f" - {row.evidence}" if row.evidence else ""
        results.append(
            {
                "question": f"{row.question}: {row.criterion}{evidence}",
                "marks_available": int(maximum) if maximum.is_integer() else maximum,
                "marks_awarded": int(numeric_awarded) if numeric_awarded.is_integer() else numeric_awarded,
                "passed": row.status == "PASS" or numeric_awarded >= maximum,
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
