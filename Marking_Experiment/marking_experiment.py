"""Standalone marking experiment engine.

This module contains the core schema, type registry, feedback templates,
and Word color theme resolver for the Marking Experiment prototype.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Word XML namespaces used for theme/color resolution.
WN = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

THEME_COLOR_NAMES = {
    "dk1": "Dark 1",
    "lt1": "Light 1",
    "dk2": "Dark 2",
    "lt2": "Light 2",
    "accent1": "Accent 1",
    "accent2": "Accent 2",
    "accent3": "Accent 3",
    "accent4": "Accent 4",
    "accent5": "Accent 5",
    "accent6": "Accent 6",
}

TINT_SHADE_NAMES = {
    # Tints are lighter variants.
    "FF": "0%",
    "E6": "10% Lighter",
    "CC": "25% Lighter",
    "99": "50% Lighter",
    "66": "60% Lighter",
    "33": "80% Lighter",
    # Shades are darker variants.
    "BF": "25% Darker",
    "7F": "50% Darker",
    "40": "75% Darker",
}

THEME_HEX_DEFAULTS = {
    "accent1": "4472C4",
    "accent2": "ED7D31",
    "accent3": "A5A5A5",
    "accent4": "FFC000",
    "accent5": "5B9BD5",
    "accent6": "70AD47",
    "dk1": "000000",
    "lt1": "FFFFFF",
    "dk2": "1F497D",
    "lt2": "EEECE1",
}

MARKING_SCHEMA: Dict[str, Any] = {
    "word": {
        "paragraph_formatting": {
            "alignment": "left|center|right|justify",
            "line_spacing": "exact or atLeast with unit pt or lines",
            "space_before": "value with unit pt",
            "space_after": "value with unit pt",
            "indent_left": "value with unit cm",
            "indent_right": "value with unit cm",
            "first_line_indent": "value with unit cm",
            "hanging_indent": "value with unit cm",
            "border": "sides/style/color/width_pt",
            "shading": "color hex",
            "tab_stop": "position_cm/alignment",
            "drop_cap": "position and lines",
        },
        "font": {
            "color": "hex or themeColor reference",
            "size": "pt",
            "name": "font name",
            "bold": "true/false",
            "italic": "true/false",
            "underline": "true/false or type",
            "strikethrough": "true/false",
            "superscript": "true/false",
            "subscript": "true/false",
            "highlight": "theme or color",
            "sentence_case": "true/false",
            "all_caps": "true/false",
        },
        "page_layout": {
            "size": "A4/A3/Letter/Custom",
            "orientation": "portrait|landscape",
            "margin": "top/bottom/left/right in cm",
            "hyphenation": "true/false",
            "columns": "count and spacing",
            "break": "page|section|column",
            "header": "contains/alignment/different_first",
            "footer": "page_number/format/alignment",
            "line_numbers": "enabled/start/interval",
        },
        "design": {
            "watermark": "text/color/layout",
            "page_border": "style/color/width_pt/apply_to",
            "background_color": "hex or theme",
            "theme": "Office theme name",
        },
        "list": {
            "list_style": "type and level",
            "bullet_char": "symbol or picture",
            "number_format": "1.|a)|I.",
            "indent_level": "level number",
            "multilevel_format": "specified level patterns",
            "list_paragraph_font": "font settings",
        },
        "table": {
            "exists": "true/false",
            "dimensions": "rows and cols",
            "merge_horizontal": "row/col_start/col_end",
            "merge_vertical": "col/row_start/row_end",
            "cell_text": "row/col/text/tolerance",
            "cell_alignment": "row/col/horizontal/vertical",
            "cell_font": "row/col/font settings",
            "cell_shading": "row/col/color",
            "cell_border": "row/col/sides/style/width_pt",
            "row_height": "row/height_cm/rule",
            "col_width": "col/width_cm",
            "table_border": "style/color/width_pt",
        },
        "object": {
            "image": {
                "exists": "true/false",
                "size": "width_cm and height_cm",
                "alignment": "left|center|right",
                "wrap": "inline|square|tight|behind|infront",
                "caption": "required/contains/position",
                "alt_text": "required/contains",
            },
            "smartart": {
                "exists": "true/false",
                "type": "hierarchy|cycle|list|process|relationship|matrix|pyramid",
                "node_text": "index and text",
            },
            "textbox": {
                "exists": "true/false",
                "text": "contains text",
                "fill_color": "hex",
                "border_color": "hex",
            },
            "shape": {
                "exists": "true/false",
                "shape_type": "rectangle|oval|arrow|...",
                "fill_color": "hex",
            },
        },
        "advanced": {
            "style_applied": "style_name and locator",
            "bookmark": "name",
            "cross_reference": "target_bookmark",
            "toc": "exists/levels/page_numbers",
            "footnote": "exists/contains",
            "endnote": "exists",
            "comment": "exists/author",
            "bibliography": "exists/source_count/style",
        },
    },
    "excel": {
        "cell": "address/text/value",
        "formula": "address/expression",
        "format": "font/border/fill",
        "merge": "range",
        "chart": "type/series/title",
        "sheet": "name/visibility",
        "page_setup": "orientation/margins",
    },
    "html": {
        "tag": "name and count",
        "attribute": "name/value",
        "style": "css property/value",
        "structure": "hierarchy or nesting",
    },
    "access": {
        "table": "fields/rows",
        "query": "sql or object properties",
        "form": "control type/label",
        "report": "layout/summary",
    },
}

class CheckOutcome(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


FEEDBACK_TEMPLATES: Dict[Tuple[str, str], Dict[str, str]] = {
    ("paragraph_formatting", "alignment"): {
        "pass": "Alignment correctly set to {expected}.",
        "fail": "Alignment was {actual}; expected {expected}.",
    },
    ("paragraph_formatting", "line_spacing"): {
        "pass": "Line spacing correctly set to {expected}.",
        "fail": "Line spacing was {actual}; expected {expected}.",
    },
    ("paragraph_formatting", "space_before"): {
        "pass": "Spacing before correctly set to {expected}.",
        "fail": "Spacing before was {actual}; expected {expected}.",
    },
    ("paragraph_formatting", "space_after"): {
        "pass": "Spacing after correctly set to {expected}.",
        "fail": "Spacing after was {actual}; expected {expected}.",
    },
    ("font", "color"): {
        "pass": "Font color correctly set to {expected_name} ({expected}).",
        "fail": "Font color was {actual_name} ({actual}); expected {expected_name} ({expected}).",
    },
    ("font", "size"): {
        "pass": "Font size correctly set to {expected} pt.",
        "fail": "Font size was {actual} pt; expected {expected} pt.",
    },
    ("font", "bold"): {
        "pass": "Bold formatting is correct.",
        "fail": "Bold formatting is incorrect.",
    },
    ("font", "italic"): {
        "pass": "Italic formatting is correct.",
        "fail": "Italic formatting is incorrect.",
    },
    ("table", "merge_horizontal"): {
        "pass": "Row {row} correctly merged from col {col_start} to {col_end}.",
        "fail": "Row {row} was not merged as expected; found {actual_span} separate cells.",
    },
    ("table", "cell_text"): {
        "pass": "Cell text correctly contains '{expected_text}'.",
        "fail": "Cell text did not match; found '{actual_text}' instead of '{expected_text}'.",
        "tolerance": "Cell text found in nearby location; merge formatting check failed separately.",
    },
    ("object", "image"): {
        "pass": "Image object fulfills the required rule.",
        "fail": "Image object does not meet the required rule.",
    },
    ("advanced", "bibliography"): {
        "pass": "Bibliography exists and matches expected style.",
        "fail": "Bibliography requirements were not met.",
    },
}


@dataclass
class CheckResult:
    question_number: str
    description: str
    marks: int
    passed: bool
    feedback: str
    actual: Optional[Any] = None
    expected: Optional[Any] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarkingSession:
    task_name: str
    program: str
    file_path: Path
    total_marks: int
    results: List[CheckResult] = field(default_factory=list)

    @property
    def score(self) -> int:
        return sum(result.marks for result in self.results if result.passed)


def resolve_theme_color_name(theme_color: Optional[str], tint: Optional[str], shade: Optional[str]) -> str:
    if theme_color:
        theme_name = THEME_COLOR_NAMES.get(theme_color, theme_color)
        modifier = None
        if tint:
            modifier = TINT_SHADE_NAMES.get(tint.upper(), f"Tint {tint}")
        elif shade:
            modifier = TINT_SHADE_NAMES.get(shade.upper(), f"Shade {shade}")
        if modifier and modifier != "0%":
            return f"{theme_name}, {modifier}"
        return theme_name
    return "Unknown theme color"


def resolve_hex_name(hex_value: Optional[str]) -> str:
    if not hex_value:
        return "Unknown color"
    return hex_value.upper()


def load_word_theme_map(docx_path: Path) -> Dict[str, str]:
    theme_map: Dict[str, str] = {}
    if not docx_path.exists():
        return theme_map

    with zipfile.ZipFile(docx_path, "r") as zf:
        try:
            theme_xml = zf.read("word/theme/theme1.xml")
        except KeyError:
            return theme_map

    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(theme_xml)
        for color_tag in root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}clrScheme/*"):
            name = color_tag.tag.split('}')[-1]
            value = None
            srgb = color_tag.find("{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr")
            if srgb is not None and "val" in srgb.attrib:
                value = srgb.attrib["val"].upper()
            if name and value:
                theme_map[name] = value
    except Exception:
        pass

    return theme_map


def format_feedback(domain: str, check_type: str, passed: bool, context: Dict[str, Any]) -> str:
    template_group = FEEDBACK_TEMPLATES.get((domain, check_type), {})
    key = "pass" if passed else "fail"
    template = template_group.get(key)
    if not template:
        return "Check completed." if passed else "Check failed."
    return template.format(**context)


if __name__ == "__main__":
    example_task = {
        "task_name": "Word Table and Font Test",
        "program": "word",
        "file": "task.docx",
        "total_marks": 10,
        "questions": [],
    }
    print("Marking Experiment schema loaded.")
    print(json.dumps(MARKING_SCHEMA["word"]["table"], indent=2))
    print("Feedback example:", format_feedback("font", "color", False, {"actual_name": "Dark Red", "actual": "C00000", "expected_name": "Accent 2, 25% Lighter", "expected": "9DC3E6"}))
