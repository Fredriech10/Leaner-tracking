"""Font rule checker for Word documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from docx import Document

from ..checker_types import CheckerResult
from .word_utils import (
    _find_paragraphs,
    _find_run,
    _match_color,
    _resolve_color_info,
    _resolve_font_theme,
    _font_xml_bool,
    _font_xml_val,
    resolve_theme_color_name,
)


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
    if check_type == "underline":
        actual = run.font.underline
        if isinstance(expected, str):
            passed = str(actual).lower().endswith(expected.lower()) if actual is not None else False
        else:
            passed = bool(actual) == bool(expected)
        return CheckerResult(passed=passed, actual=str(actual) if actual is not None else None, details={"type": check_type})
    if check_type == "strikethrough":
        actual = bool(run.font.strike)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "double_strikethrough":
        actual = _font_xml_bool(run, "dstrike")
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "superscript":
        actual = bool(run.font.superscript)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "subscript":
        actual = bool(run.font.subscript)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "all_caps":
        actual = bool(run.font.all_caps)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "small_caps":
        actual = bool(run.font.small_caps)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "shadow":
        actual = bool(run.font.shadow)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "outline":
        actual = bool(run.font.outline)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "emboss":
        actual = bool(run.font.emboss)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "hidden":
        actual = bool(run.font.hidden)
        passed = actual == bool(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "font_name":
        actual = run.font.name
        passed = str(actual).lower() == str(expected).lower() if actual else False
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "font_theme":
        actual = _resolve_font_theme(run)
        passed = str(actual).lower() == str(expected).lower() if actual else False
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "character_spacing":
        actual = _font_xml_val(run, "spacing")
        passed = str(actual) == str(expected)
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
    if check_type == "kerning":
        actual = _font_xml_val(run, "kerning")
        passed = str(actual) == str(expected)
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