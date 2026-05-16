"""Core engine and checker skeleton for Marking Experiment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .checks import get_rule_checker
from .checker_types import BaseChecker, CheckerResult
from .marking_experiment import CheckResult, CheckOutcome, MarkingSession, format_feedback


class ExcelChecker(BaseChecker):
    program = "excel"

    def check(
        self,
        domain: str,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        return CheckerResult(
            passed=False,
            actual=None,
            details={
                "domain": domain,
                "type": check_type,
                "target": target,
                "expected": expected,
                "reason": "Excel checks are not implemented yet.",
            },
        )


class HTMLChecker(BaseChecker):
    program = "html"

    def check(
        self,
        domain: str,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        return CheckerResult(
            passed=False,
            actual=None,
            details={
                "domain": domain,
                "type": check_type,
                "target": target,
                "expected": expected,
                "reason": "HTML checks are not implemented yet.",
            },
        )


class AccessChecker(BaseChecker):
    program = "access"

    def check(
        self,
        domain: str,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        return CheckerResult(
            passed=False,
            actual=None,
            details={
                "domain": domain,
                "type": check_type,
                "target": target,
                "expected": expected,
                "reason": "Access checks are not implemented yet.",
            },
        )


from .word_checker import WordChecker


class MarkingEngine:
    def __init__(self, checkers: Optional[List[BaseChecker]] = None):
        if checkers is None:
            checkers = [WordChecker(), ExcelChecker(), HTMLChecker(), AccessChecker()]
        self.checkers = checkers

    def load_task_definition(self, task_path: Path) -> Dict[str, Any]:
        if not task_path.exists():
            raise FileNotFoundError(f"Task definition not found: {task_path}")
        with task_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def run_task(self, task_definition: Dict[str, Any], file_path: Path) -> MarkingSession:
        program = task_definition.get("program", "word").lower()
        session = MarkingSession(
            task_name=task_definition.get("task_name", "Experimental Marking Task"),
            program=program,
            file_path=file_path,
            total_marks=int(task_definition.get("total_marks", 0)),
        )

        rule_checker = get_rule_checker(program)

        import traceback
        print(f"[Marking_Experiment] Running engine program={program} file={file_path} questions={len(task_definition.get('questions', []))}")
        for question in task_definition.get("questions", []):
            try:
                results = self._run_question(question, rule_checker, file_path)
                session.results.extend(results)
            except Exception as exc:
                tb = traceback.format_exc()
                print(
                    "[Marking_Experiment] Engine error while running question\n"
                    f"  file={file_path}\n"
                    f"  program={program}\n"
                    f"  question={question}\n"
                    f"  exc={exc}\n"
                    f"  traceback={tb}"
                )
                # Continue marking, but mark engine-level failure as a skipped block.
                # We avoid crashing the UI.
                continue

        return session


    def _find_checker(self, program: str) -> Optional[BaseChecker]:
        for checker in self.checkers:
            if checker.can_handle(program):
                return checker
        return None

    def _run_question(
        self,
        question: Dict[str, Any],
        rule_checker: Any,
        file_path: Path,
    ) -> List[CheckResult]:
        question_number = str(question.get("question_number", "0"))
        description = str(question.get("description", "No description provided."))
        rules = question.get("rules") if isinstance(question.get("rules"), list) else [
            {
                "domain": question.get("domain", ""),
                "type": question.get("type", ""),
                "target": question.get("target", {}),
                "expected": question.get("expected"),
                "marks": int(question.get("marks", 1)),
                "description": description,
            }
        ]

        results: List[CheckResult] = []
        for idx, rule in enumerate(rules, start=1):
            domain = str(rule.get("domain", ""))
            check_type = str(rule.get("type", rule.get("property", "")))
            target = rule.get("target", {}) or {}
            expected = rule.get("expected")
            marks = int(rule.get("marks", 1))
            rule_description = str(rule.get("description", description))
            rule_number = question_number if len(rules) == 1 else f"{question_number}.{idx}"

            try:
                checker_result = rule_checker(file_path, rule)
                details = checker_result.details or {}
                feedback_context = {
                    "expected": expected,
                    "actual": checker_result.actual,
                    "expected_name": expected if isinstance(expected, str) else str(expected),
                    "actual_name": checker_result.actual if isinstance(checker_result.actual, str) else str(checker_result.actual),
                    **details,
                }
                feedback = format_feedback(domain, check_type, checker_result.passed, feedback_context)
                outcome = CheckOutcome.PASS if checker_result.passed else CheckOutcome.FAIL
                passed = checker_result.passed
                actual = checker_result.actual
            except Exception as exc:
                # Mark the check as unable to be performed and continue.
                import traceback
                tb = traceback.format_exc()
                outcome = CheckOutcome.SKIPPED
                passed = False
                actual = None
                details = {"reason": "Check unable to be performed", "error": str(exc), "traceback": tb}
                feedback = f"SKIPPED: Unable to perform check for {domain}/{check_type}: {exc}"
            # If the checker signals failure due to unsupported/unknown rule mapping, treat as SKIPPED.
            if not ("error" in (details or {})) and isinstance(details, dict) and details.get("reason"):
                r = str(details.get("reason", "")).lower()
                if "not implemented" in r or "unsupported" in r or "not readable" in r:
                    outcome = CheckOutcome.SKIPPED
                    passed = False
                    if actual is None:
                        actual = None
                    feedback = f"SKIPPED: {details.get('reason')}"


            results.append(
                CheckResult(
                    question_number=rule_number,
                    description=rule_description,
                    marks=marks,
                    passed=passed,

                    feedback=feedback,
                    actual=actual,
                    expected=expected,
                    details=details,
                )
            )


        return results


def build_example_task() -> Dict[str, Any]:
    return {
        "task_name": "Experimental Word Marking Task",
        "program": "word",
        "file": "sample.docx",
        "total_marks": 5,
        "questions": [
            {
                "question_number": "1",
                "description": "Check paragraph alignment under the heading 'Introduction'.",
                "marks": 1,
                "domain": "paragraph_formatting",
                "type": "alignment",
                "target": {"locator": "after_heading", "value": "Introduction"},
                "expected": "justify",
            }
        ],
    }


if __name__ == "__main__":
    engine = MarkingEngine()
    sample_task = build_example_task()
    sample_path = Path("sample.docx")
    session = engine.run_task(sample_task, sample_path)
    print(f"Task: {session.task_name}")
    print(f"Score: {session.score} / {session.total_marks}")
    for result in session.results:
        print(result)
