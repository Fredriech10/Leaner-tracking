"""Shared checker types for Marking Experiment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


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
