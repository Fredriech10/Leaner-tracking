"""Core engine and checker skeleton for Marking Experiment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .marking_experiment import CheckResult, MarkingSession, format_feedback


@dataclass
class CheckerResult:
    passed: bool
    actual: Any = None
    details: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class BaseChecker:
    program = ""

    def can_handle(self, program: str) -> bool:
        return program.lower() == self.program

    def check(
        self,
        domain: str,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        raise NotImplementedError("Checker must implement check()")


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

        checker = self._find_checker(program)
        if checker is None:
            raise ValueError(f"No checker available for program: {program}")

        for question in task_definition.get("questions", []):
            result = self._run_question(question, checker, file_path)
            session.results.append(result)

        return session

    def _find_checker(self, program: str) -> Optional[BaseChecker]:
        for checker in self.checkers:
            if checker.can_handle(program):
                return checker
        return None

    def _run_question(
        self,
        question: Dict[str, Any],
        checker: BaseChecker,
        file_path: Path,
    ) -> CheckResult:
        domain = str(question.get("domain", ""))
        check_type = str(question.get("type", ""))
        target = question.get("target", {})
        expected = question.get("expected")
        marks = int(question.get("marks", 1))
        description = str(question.get("description", "No description provided."))

        checker_result = checker.check(domain, check_type, target, expected, file_path)

        details = checker_result.details or {}
        feedback_context = {
            "expected": expected,
            "actual": checker_result.actual,
            "expected_name": expected if isinstance(expected, str) else str(expected),
            "actual_name": checker_result.actual if isinstance(checker_result.actual, str) else str(checker_result.actual),
            **details,
        }

        feedback = format_feedback(domain, check_type, checker_result.passed, feedback_context)
        return CheckResult(
            question_number=question.get("question_number", "0"),
            description=description,
            marks=marks,
            passed=checker_result.passed,
            feedback=feedback,
            actual=checker_result.actual,
            expected=expected,
            details=checker_result.details or {},
        )


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
