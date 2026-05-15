"""Font rule checker for Word documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from docx import Document

from checker_types import CheckerResult
from .word_utils import _find_paragraphs, _find_run, _match_color, _resolve_color_info, resolve_theme_color_name


def check_font_rule(rule: Dict[str, Any], file_path: Path) -> CheckerResult:
    document = Document(file_path)
    check_type = str(rule.get("type", ""))
    target = rule.get("target", {}) or {}
    expected = rule.get("expected")

    paragraphs = _find_paragraphs(document, target)
    if not paragraphs:
        return CheckerResult(passed=False, details={"reason": "Font target not found."})
    run = _find_run(paragraphs)
    if run is None:
        return CheckerResult(passed=False, details={"reason": "No run found for font target."})

    actual = None
    actual_name = None
    theme_name = None
    if check_type == "color":
        theme_color, theme_tint, theme_shade, value = _resolve_color_info(run, file_path)
        actual = value
        if theme_color:
            theme_name = resolve_theme_color_name(theme_color, theme_tint, theme_shade)
        passed = _match_color(expected, actual, theme_name)
        return CheckerResult(
            passed=passed,
            actual=actual,
            details={"actual_theme": theme_name, "type": check_type},
        )
    if check_type == "size":
        actual = run.font.size.pt if run.font.size else None
        passed = float(actual) == float(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "bold":
        actual = bool(run.font.bold)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "italic":
        actual = bool(run.font.italic)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "bold_and_color":
        bold_ok = bool(run.font.bold)
        theme_color, theme_tint, theme_shade, value = _resolve_color_info(run, file_path)
        theme_name = resolve_theme_color_name(theme_color, theme_tint, theme_shade) if theme_color else None
        exp_color = expected.get("color", "") if isinstance(expected, dict) else ""
        color_ok = _match_color(exp_color, value, theme_name)
        passed = bold_ok and color_ok
        return CheckerResult(passed=passed, actual={"bold": bold_ok, "color": value}, details={"type": check_type})
    return CheckerResult(passed=False, details={"reason": "Unsupported font check."})