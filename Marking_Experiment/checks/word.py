"""Word rule checker entry point for Marking Experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from .font import check_font_rule
from .paragraph_formatting import check_paragraph_formatting_rule
from .table import check_table_rule
from .list import check_list_rule
from .document import check_document_rule
from .object import check_object_rule
from .advanced import check_advanced_rule


def _normalize_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    if "type" not in rule and "property" in rule:
        normalized = dict(rule)
        normalized["type"] = normalized["property"]
        return normalized
    return rule


def check_word_rule(file_path: Path, rule: Dict[str, Any]):
    rule = _normalize_rule(rule)
    domain = str(rule.get("domain", ""))

    # Dispatch to domain-specific checkers
    if domain == "font":
        return check_font_rule(rule, file_path)
    elif domain == "paragraph_formatting":
        return check_paragraph_formatting_rule(rule, file_path)
    elif domain == "table":
        return check_table_rule(rule, file_path)
    elif domain == "list":
        return check_list_rule(rule, file_path)
    elif domain == "document":
        return check_document_rule(rule, file_path)
    elif domain == "object":
        return check_object_rule(rule, file_path)
    elif domain == "advanced":
        return check_advanced_rule(rule, file_path)
    else:
        # Fallback for unknown domains
        from ..checker_types import CheckerResult
        return CheckerResult(passed=False, details={"reason": f"Unknown domain: {domain}"})


def get_word_rule_checker(program: str) -> Callable[[Path, Dict[str, Any]], Any]:
    if str(program).lower() == "word":
        return check_word_rule
    raise ValueError(f"Unsupported rule checker program: {program}")
