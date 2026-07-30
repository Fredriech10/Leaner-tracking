"""Task checker module for Marking Experiment.

This module is responsible for loading a task JSON, validating its structure,
and running the task checks against the appropriate program checker.
It also exposes a stable enum for check outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .checks import get_rule_checker
from .marking_experiment import CheckOutcome


class TaskValidationError(Exception):
    pass


@dataclass
class CheckStatus:
    question_number: str
    description: str
    domain: str
    type: str
    target: Dict[str, Any]
    expected: Any
    actual: Any
    marks: int
    passed: bool
    outcome: CheckOutcome
    details: Dict[str, Any]


def validate_task_definition(task_definition: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []

    if not isinstance(task_definition, dict):
        raise TaskValidationError("Task definition must be a JSON object.")

    if "program" not in task_definition:
        warnings.append("Task definition missing 'program'.")
    if "questions" not in task_definition:
        warnings.append("Task definition missing 'questions'.")
    elif not isinstance(task_definition["questions"], list):
        warnings.append("Task definition 'questions' must be a list.")

    for idx, question in enumerate(task_definition.get("questions", []), start=1):
        if not isinstance(question, dict):
            warnings.append(f"Question {idx} is not an object.")
            continue
        for field in ["question_number", "description", "domain", "type", "target", "expected", "marks"]:
            if field not in question:
                warnings.append(f"Question {idx} missing '{field}'.")
        if not isinstance(question.get("target", {}), dict):
            warnings.append(f"Question {idx} target must be an object.")
    return warnings


def get_checker_for_program(program: str):
    try:
        return get_rule_checker(program)
    except ValueError as exc:
        raise TaskValidationError(str(exc)) from exc


def run_task_checks(
    task_definition: Dict[str, Any],
    file_path: Path,
    checker: Optional[Any] = None,
) -> List[CheckStatus]:
    if checker is None:
        checker = get_checker_for_program(task_definition.get("program", "word"))

    results: List[CheckStatus] = []
    for question in task_definition.get("questions", []):
        question_number = str(question.get("question_number", ""))
        description = str(question.get("description", ""))
        rules = question.get("rules") if isinstance(question.get("rules"), list) else [question]

        for idx, rule in enumerate(rules, start=1):
            domain = str(rule.get("domain", ""))
            check_type = str(rule.get("type", rule.get("property", "")))
            target = rule.get("target", {}) or {}
            expected = rule.get("expected")
            marks = int(rule.get("marks", question.get("marks", 1)))
            rule_description = str(rule.get("description", description))
            rule_number = question_number if len(rules) == 1 else f"{question_number}.{idx}"

            try:
                checker_result = checker(file_path, rule)
                passed = bool(checker_result.passed)
                outcome = CheckOutcome.PASS if passed else CheckOutcome.FAIL
                actual = checker_result.actual
                details = checker_result.details or {}
            except Exception as exc:
                # Keep error in output details, but also emit full traceback to terminal/log.
                import traceback
                tb = traceback.format_exc()

                print(
                    "[Marking_Experiment] Check ERROR\n"
                    f"  program={task_definition.get('program')}\n"
                    f"  file={file_path}\n"
                    f"  question={question_number}\n"
                    f"  rule_index={idx}\n"
                    f"  domain={domain}\n"
                    f"  type={check_type}\n"
                    f"  target={target}\n"
                    f"  expected={expected}\n"
                    f"  exc={exc}\n"
                    f"  traceback={tb}"
                )

                passed = False
                outcome = CheckOutcome.ERROR
                actual = None
                details = {"error": str(exc), "traceback": tb}


            results.append(
                CheckStatus(
                    question_number=rule_number,
                    description=rule_description,
                    domain=domain,
                    type=check_type,
                    target=target,
                    expected=expected,
                    actual=actual,
                    marks=marks,
                    passed=passed,
                    outcome=outcome,
                    details=details,
                )
            )
    return results


def summarize_check_results(results: List[CheckStatus]) -> Dict[str, Any]:
    summary = {
        "total_questions": len(results),
        "passed": sum(1 for r in results if r.outcome == CheckOutcome.PASS),
        "failed": sum(1 for r in results if r.outcome == CheckOutcome.FAIL),
        "errors": sum(1 for r in results if r.outcome == CheckOutcome.ERROR),
        "total_marks": sum(r.marks for r in results),
        "earned_marks": sum(r.marks for r in results if r.outcome == CheckOutcome.PASS),
    }
    return summary
