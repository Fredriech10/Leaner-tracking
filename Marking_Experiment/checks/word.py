"""Word rule checker entry point for Marking Experiment."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Dict

from ..word_checker import WordChecker


def _normalize_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    if "type" not in rule and "property" in rule:
        normalized = dict(rule)
        normalized["type"] = normalized["property"]
        return normalized
    description = str(rule.get("description", "")).lower()
    if rule.get("domain") == "font" and rule.get("type") == "bold" and "bold" in description:
        color_match = re.search(r"\b(red|blue|green|black|yellow)\b", description)
        text_match = re.search(r'"([^"]+)"', str(rule.get("description", "")))
        if color_match:
            normalized = dict(rule)
            normalized["type"] = "bold_and_color"
            normalized["target"] = {"locator": "contains_text", "value": text_match.group(1)} if text_match else normalized.get("target", {})
            normalized["expected"] = {"bold": True, "color": color_match.group(1)}
            return normalized
    if rule.get("domain") == "document" and rule.get("type") == "page_border" and "border" in description and "page" not in description:
        normalized = dict(rule)
        normalized["domain"] = "object"
        normalized["type"] = "image_border"
        width_match = re.search(r"(\d+(?:\.\d+)?)\s*pt", description)
        color_match = re.search(r"\b(red|blue|green|black|yellow|white)\b", description)
        normalized["expected"] = {
            "width_pt": float(width_match.group(1)) if width_match else 1.0,
            "color": color_match.group(1) if color_match else None,
        }
        return normalized
    return rule


def check_word_rule(file_path: Path, rule: Dict[str, Any]):
    rule = _normalize_rule(rule)
    domain = str(rule.get("domain", ""))
    check_type = str(rule.get("type", ""))
    target = rule.get("target", {}) or {}
    expected = rule.get("expected")
    return WordChecker().check(domain, check_type, target, expected, file_path)


def get_word_rule_checker(program: str) -> Callable[[Path, Dict[str, Any]], Any]:
    if str(program).lower() == "word":
        return check_word_rule
    raise ValueError(f"Unsupported rule checker program: {program}")
