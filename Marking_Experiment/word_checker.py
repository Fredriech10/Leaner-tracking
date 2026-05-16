"""Word document checker for Marking Experiment."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.oxml.ns import qn
from lxml import etree
from zipfile import ZipFile

from .checker_types import BaseChecker, CheckerResult
from .marking_experiment import resolve_theme_color_name
from .utils import (
    compare_numeric, emu_to_pt, emu_to_cm, cm_to_emu, 
    normalize_hex_color, TOLERANCE_PT, TOLERANCE_CM
)
from .targeting import find_best_candidate_paragraph, find_table

logger = logging.getLogger(__name__)


NAMESPACES = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

ALIGNMENT_MAP = {
    WD_PARAGRAPH_ALIGNMENT.LEFT: "left",
    WD_PARAGRAPH_ALIGNMENT.CENTER: "center",
    WD_PARAGRAPH_ALIGNMENT.RIGHT: "right",
    WD_PARAGRAPH_ALIGNMENT.JUSTIFY: "justify",
    WD_PARAGRAPH_ALIGNMENT.DISTRIBUTE: "justify",
    WD_PARAGRAPH_ALIGNMENT.THAI_JUSTIFY: "justify",
}


def xml_find(element, xpath: str):
    return element.find(xpath, namespaces=NAMESPACES)


def _xml_tree_from_oxml(oxml_element) -> Optional[etree._Element]:
    if oxml_element is None:
        return None
    return etree.fromstring(oxml_element.xml.encode("utf-8"))


def _read_docx_part(file_path: Path, part_name: str) -> Optional[str]:
    try:
        with ZipFile(file_path, "r") as zf:
            return zf.read(part_name).decode("utf-8")
    except Exception:
        return None


class WordChecker(BaseChecker):
    program = "word"

    def _load_document(self, file_path: Path) -> Document:
        return Document(file_path)

    def _resolve_color_info(self, run, file_path: Path) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        xml = run._r.xml
        tree = etree.fromstring(xml.encode("utf-8"))
        color_element = tree.find(".//w:color", namespaces=NAMESPACES)
        if color_element is None:
            return None, None, None, None
        theme_color = color_element.get(qn("w:themeColor"))
        theme_tint = color_element.get(qn("w:themeTint"))
        theme_shade = color_element.get(qn("w:themeShade"))
        value = color_element.get(qn("w:val"))
        if value:
            value = normalize_hex_color(value)
        return theme_color, theme_tint, theme_shade, value

    def _match_color(self, expected: Any, actual_hex: Optional[str], actual_theme_name: Optional[str]) -> bool:
        named_colors = {
            "black": {"000000"},
            "blue": {"0000FF", "0070C0", "4472C4", "1F497D"},
            "green": {"008000", "00B050", "70AD47"},
            "red": {"FF0000", "C00000"},
            "white": {"FFFFFF"},
            "yellow": {"FFFF00", "FFC000"},
        }
        if isinstance(expected, str) and actual_hex:
            allowed = named_colors.get(expected.strip().lower())
            if allowed and actual_hex.upper() in allowed:
                return True
            theme_aliases = {
                "black": {"tx1", "dk1"},
                "white": {"bg1", "lt1"},
            }
            if actual_hex.lower() in theme_aliases.get(expected.strip().lower(), set()):
                return True
        expected_value = normalize_hex_color(str(expected)) if isinstance(expected, str) else None
        if expected_value and actual_hex:
            if expected_value == actual_hex:
                return True
        if isinstance(expected, str) and actual_theme_name:
            return expected.lower() == actual_theme_name.lower()
        return False

    def _target_locator(self, target: Dict[str, Any]) -> Tuple[str, Any]:
        locator = target.get("locator")
        if isinstance(locator, dict):
            pair = next(iter(locator.items()))
            return pair[0], pair[1]
        return locator, target.get("value")

    def _find_paragraphs(self, document: Document, target: Dict[str, Any]) -> List[Any]:
        """Find paragraphs using robust targeting with fallbacks.
        
        Uses the targeting module for intelligent paragraph discovery.
        """
        try:
            best_para = find_best_candidate_paragraph(document, target)
            if best_para:
                return [best_para]
        except Exception as e:
            logger.warning(f"Error in paragraph targeting: {e}")
        
        # Fallback to first non-empty paragraph
        for p in document.paragraphs:
            if p.text.strip():
                return [p]
        
        return []

    def _find_table(self, document: Document, target: Dict[str, Any]) -> Optional[Any]:
        """Find table using robust targeting."""
        try:
            return find_table(document, target)
        except Exception as e:
            logger.warning(f"Error finding table: {e}")
            # Fallback to first table
            if document.tables:
                return document.tables[0]
        return None

    def _get_table_cell(self, table, row: int, col: int) -> Optional[Any]:
        try:
            return table.rows[row].cells[col]
        except (IndexError, ValueError):
            return None

    def _cell_grid_span(self, cell) -> int:
        tcPr = cell._tc.tcPr
        if tcPr is None:
            return 1
        grid_span = tcPr.find(qn("w:gridSpan"))
        if grid_span is not None and grid_span.get(qn("w:val")):
            return int(grid_span.get(qn("w:val")))
        return 1

    def _cell_vmerge(self, cell) -> bool:
        tcPr = cell._tc.tcPr
        if tcPr is None:
            return False
        vmerge = tcPr.find(qn("w:vMerge"))
        return vmerge is not None

    def _find_run(self, paragraphs, text: Optional[str] = None):
        for paragraph in paragraphs:
            for run in paragraph.runs:
                if not text or text.lower() in run.text.lower():
                    return run
        return None

    def _document_text(self, document: Document, file_path: Path) -> str:
        parts = [p.text for p in document.paragraphs if p.text]
        for section in document.sections:
            for part in (
                section.header,
                section.even_page_header,
                section.first_page_header,
                section.footer,
                section.even_page_footer,
                section.first_page_footer,
            ):
                try:
                    parts.extend(p.text for p in part.paragraphs if p.text)
                except Exception:
                    continue

        for part_name in (
            "word/document.xml",
            "word/header1.xml",
            "word/header2.xml",
            "word/header3.xml",
            "word/footer1.xml",
            "word/footer2.xml",
            "word/footer3.xml",
        ):
            xml = _read_docx_part(file_path, part_name)
            if not xml:
                continue
            try:
                root = etree.fromstring(xml.encode("utf-8"))
            except Exception:
                continue
            for node in root.iter(f"{{{NAMESPACES['w']}}}t"):
                if node.text:
                    parts.append(node.text)
            for node in root.iter(f"{{{NAMESPACES['w']}}}instrText"):
                if node.text:
                    parts.append(node.text)
        return "\n".join(parts)

    def _paragraph_num_pr(self, paragraph):
        pPr = paragraph._p.pPr
        if pPr is None:
            return None
        return xml_find(pPr, "w:numPr")

    def _get_list_properties(self, paragraph, document):
        numPr = self._paragraph_num_pr(paragraph)
        if numPr is None:
            return None

        numId_el = xml_find(numPr, "w:numId")
        ilvl_el = xml_find(numPr, "w:ilvl")
        if numId_el is None:
            return None

        num_id = numId_el.get(qn("w:val"))
        level = int(ilvl_el.get(qn("w:val"))) if ilvl_el is not None else 0

        if not hasattr(document.part, "numbering_part") or document.part.numbering_part is None:
            return {"num_id": num_id, "level": level}
        numbering_xml = document.part.numbering_part.element.xml
        numbering_tree = etree.fromstring(numbering_xml.encode("utf-8"))
        num_nodes = numbering_tree.xpath(f".//w:num[@w:numId='{num_id}']", namespaces=NAMESPACES)
        if not num_nodes:
            return {"num_id": num_id, "level": level}

        abstract_id = num_nodes[0].xpath("./w:abstractNumId", namespaces=NAMESPACES)
        if not abstract_id:
            return {"num_id": num_id, "level": level}

        abstract_id = abstract_id[0].get(qn("w:val"))
        abstract_nodes = numbering_tree.xpath(f".//w:abstractNum[@w:abstractNumId='{abstract_id}']", namespaces=NAMESPACES)
        if not abstract_nodes:
            return {"num_id": num_id, "level": level}

        lvl_nodes = abstract_nodes[0].xpath(f".//w:lvl[@w:ilvl='{level}']", namespaces=NAMESPACES)
        if not lvl_nodes:
            return {"num_id": num_id, "level": level}

        num_fmt_el = lvl_nodes[0].find("./w:numFmt", namespaces=NAMESPACES)
        lvl_text_el = lvl_nodes[0].find("./w:lvlText", namespaces=NAMESPACES)
        num_fmt = num_fmt_el.get(qn("w:val")) if num_fmt_el is not None else None
        lvl_text = lvl_text_el.get(qn("w:val")) if lvl_text_el is not None else None

        if num_fmt is None:
            list_type = "unknown"
        elif num_fmt.lower() == "bullet":
            list_type = "bullet"
        elif num_fmt.lower() in {"decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman"}:
            list_type = "number"
        else:
            list_type = "multilevel"

        return {
            "num_id": num_id,
            "level": level,
            "num_fmt": num_fmt,
            "lvl_text": lvl_text,
            "type": list_type,
        }

    def _match_run_font(self, run, expected: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        actual: Dict[str, Any] = {}
        passed = True

        if "bold" in expected:
            actual["bold"] = bool(run.font.bold)
            passed = passed and actual["bold"] == bool(expected["bold"])
        if "italic" in expected:
            actual["italic"] = bool(run.font.italic)
            passed = passed and actual["italic"] == bool(expected["italic"])
        if "size" in expected:
            actual["size"] = run.font.size.pt if run.font.size else None
            passed = passed and float(actual["size"] or 0) == float(expected["size"])
        if "color" in expected:
            theme_color, theme_tint, theme_shade, value = self._resolve_color_info(run, None)
            actual["color"] = value
            theme_name = resolve_theme_color_name(theme_color, theme_tint, theme_shade) if theme_color else None
            passed = passed and self._match_color(expected["color"], value, theme_name)
        return passed, actual

    def _check_list(
        self,
        document: Document,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
    ) -> CheckerResult:
        paragraphs = self._find_paragraphs(document, target)
        if not paragraphs:
            return CheckerResult(passed=False, details={"reason": "List target not found."})
        paragraph = paragraphs[0]
        props = self._get_list_properties(paragraph, document)
        if props is None:
            return CheckerResult(passed=False, details={"reason": "Paragraph is not a list item."})

        if check_type == "list_style":
            expected_type = str(expected.get("type", "")).lower()
            expected_level = int(expected.get("level", 0))
            actual_type = props.get("type")
            actual_level = props.get("level")
            passed = actual_type == expected_type and actual_level == expected_level
            return CheckerResult(passed=passed, actual={"type": actual_type, "level": actual_level}, details={"type": check_type})

        if check_type == "bullet_char":
            actual = props.get("lvl_text")
            # Handle Wingdings check — expected may be a unicode char or the string "wingdings"
            if isinstance(expected, str) and expected.lower() == "wingdings":
                # Check if the font used for the bullet is Wingdings
                num_id = props.get("num_id")
                level = props.get("level", 0)
                passed = False
                if hasattr(document.part, "numbering_part") and document.part.numbering_part:
                    numbering_xml = document.part.numbering_part.element.xml
                    numbering_tree = etree.fromstring(numbering_xml.encode("utf-8"))
                    num_nodes = numbering_tree.xpath(f".//w:num[@w:numId='{num_id}']", namespaces=NAMESPACES)
                    if num_nodes:
                        abstract_id_el = num_nodes[0].xpath("./w:abstractNumId", namespaces=NAMESPACES)
                        if abstract_id_el:
                            abstract_id = abstract_id_el[0].get(qn("w:val"))
                            abstract_nodes = numbering_tree.xpath(f".//w:abstractNum[@w:abstractNumId='{abstract_id}']", namespaces=NAMESPACES)
                            if abstract_nodes:
                                lvl_nodes = abstract_nodes[0].xpath(f".//w:lvl[@w:ilvl='{level}']", namespaces=NAMESPACES)
                                if lvl_nodes:
                                    rFonts = lvl_nodes[0].find(".//w:rFonts", namespaces=NAMESPACES)
                                    if rFonts is not None:
                                        font_val = rFonts.get(qn("w:ascii"), "") or rFonts.get(qn("w:hAnsi"), "")
                                        passed = "wingdings" in font_val.lower()
                return CheckerResult(passed=passed, actual={"lvl_text": actual, "font_checked": True}, details={"type": check_type})
            passed = str(expected).strip() == str(actual).strip()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        if check_type == "indent_level":
            actual = props.get("level")
            passed = int(expected) == int(actual)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        if check_type == "list_paragraph_font":
            run = self._find_run([paragraph])
            if run is None:
                return CheckerResult(passed=False, details={"reason": "No run found in list paragraph."})
            passed, actual = self._match_run_font(run, expected)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        return CheckerResult(passed=False, details={"reason": "Unsupported list check."})

    def _check_para_border(self, paragraph, expected: Any, file_path: Path) -> Tuple[bool, Any]:
        """Check paragraph border via raw XML."""
        COLOUR_MAP = {
            "blue": ["0070c0", "0000ff", "4472c4", "1f3864"],
            "red": ["ff0000", "c00000"],
            "green": ["00b050", "008000"],
            "black": ["000000"],
            "yellow": ["ffff00", "ffc000"],
        }
        WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        try:
            p_xml = etree.fromstring(paragraph._p.xml.encode("utf-8"))
        except Exception:
            return False, None
        pBdr = p_xml.find(f".//{{{WNS}}}pBdr")
        if pBdr is None:
            return False, {"reason": "No paragraph border found"}
        sides = ["top", "bottom", "left", "right"]
        actual = {}
        for side in sides:
            el = pBdr.find(f"{{{WNS}}}{side}")
            if el is not None:
                actual[side] = {
                    "style": el.get(f"{{{WNS}}}val", ""),
                    "color": el.get(f"{{{WNS}}}color", "").lower(),
                    "sz": el.get(f"{{{WNS}}}sz", ""),  # in 1/8 pt
                }
        if not actual:
            return False, {"reason": "No border sides found"}
        passed = True
        if isinstance(expected, dict):
            exp_style = expected.get("style")
            exp_color = expected.get("color", "").lower() if expected.get("color") else None
            exp_width = expected.get("width_pt")
            for side_data in actual.values():
                if exp_style and exp_style.lower() not in side_data["style"].lower():
                    passed = False
                if exp_color:
                    hex_val = side_data["color"]
                    allowed = COLOUR_MAP.get(exp_color, [exp_color])
                    if hex_val not in allowed:
                        passed = False
                if exp_width:
                    try:
                        actual_pt = int(side_data["sz"]) / 8.0
                        if abs(actual_pt - exp_width) > 0.5:
                            passed = False
                    except Exception:
                        pass
        return passed, actual

    def _check_para_shading(self, paragraph, expected: Any) -> Tuple[bool, Any]:
        """Check paragraph shading/fill via raw XML."""
        SHADING_MAP = {
            "light grey": ["d9d9d9", "bfbfbf", "f2f2f2", "d3d3d3"],
            "light gray": ["d9d9d9", "bfbfbf", "f2f2f2", "d3d3d3"],
            "grey": ["808080", "a5a5a5", "d9d9d9"],
            "gray": ["808080", "a5a5a5", "d9d9d9"],
            "blue": ["0070c0", "0000ff", "4472c4"],
            "yellow": ["ffff00", "ffc000"],
        }
        WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        try:
            p_xml = etree.fromstring(paragraph._p.xml.encode("utf-8"))
        except Exception:
            return False, None
        shd = p_xml.find(f".//{{{WNS}}}shd")
        if shd is None:
            return False, {"reason": "No shading found"}
        fill = shd.get(f"{{{WNS}}}fill", "").lower()
        theme_color = shd.get(f"{{{WNS}}}themeFill", "")
        actual = {"fill": fill, "theme": theme_color}
        if isinstance(expected, dict):
            exp_color = expected.get("color", "any").lower()
            if exp_color == "any":
                passed = bool(fill) and fill != "auto"
            else:
                allowed = SHADING_MAP.get(exp_color, [exp_color])
                passed = fill in allowed or any(a in fill for a in allowed)
        else:
            passed = bool(fill) and fill != "auto"
        return passed, actual

    def _check_drop_cap(self, paragraph, expected: Any) -> Tuple[bool, Any]:
        """Check drop cap via raw XML — looks for w:framePr with w:dropCap."""
        WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        try:
            p_xml = etree.fromstring(paragraph._p.xml.encode("utf-8"))
        except Exception:
            return False, None
        frame_pr = p_xml.find(f".//{{{WNS}}}framePr")
        if frame_pr is None:
            return False, {"reason": "No drop cap (framePr) found"}
        drop_cap = frame_pr.get(f"{{{WNS}}}dropCap", "")
        lines = frame_pr.get(f"{{{WNS}}}lines", "")
        actual = {"dropCap": drop_cap, "lines": lines}
        if not drop_cap or drop_cap == "none":
            return False, actual
        passed = True
        if isinstance(expected, dict) and expected.get("lines"):
            try:
                passed = int(lines) == int(expected["lines"])
            except Exception:
                pass
        return passed, actual

    def _check_bookmark(
        self,
        file_path: Path,
        expected: Any,
    ) -> CheckerResult:
        xml = _read_docx_part(file_path, "word/document.xml")
        if xml is None:
            return CheckerResult(passed=False, details={"reason": "Document XML not found."})
        root = etree.fromstring(xml.encode("utf-8"))
        name = expected.get("name") if isinstance(expected, dict) else str(expected)
        nodes = root.xpath(f'.//w:bookmarkStart[@w:name="{name}"]', namespaces=NAMESPACES)
        passed = bool(nodes)
        return CheckerResult(passed=passed, actual=len(nodes), details={"expected_name": name})

    def _check_bibliography(
        self,
        file_path: Path,
        expected: Any,
    ) -> CheckerResult:
        xml = _read_docx_part(file_path, "word/bibliography.xml")
        if xml is None:
            return CheckerResult(passed=False, details={"reason": "Bibliography part not found."})
        root = etree.fromstring(xml.encode("utf-8"))
        sources = root.xpath('.//*[local-name()="source"]')
        count = len(sources)
        expected_count = 1
        if isinstance(expected, dict) and expected.get("source_count") is not None:
            expected_count = int(expected.get("source_count"))
        passed = count >= expected_count
        return CheckerResult(passed=passed, actual=count, details={"expected_source_count": expected_count})

    def _check_paragraph_formatting(
        self,
        document: Document,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        paragraphs = self._find_paragraphs(document, target)
        if not paragraphs:
            return CheckerResult(passed=False, details={"reason": "Paragraph target not found."})
        paragraph = paragraphs[0]
        actual = None
        passed = False

        if check_type == "alignment":
            actual = ALIGNMENT_MAP.get(paragraph.alignment, "left")
            passed = actual == str(expected).lower()
            # If not found on target paragraph, scan all body paragraphs
            if not passed:
                for p in document.paragraphs:
                    if ALIGNMENT_MAP.get(p.alignment, "left") == str(expected).lower():
                        passed = True
                        actual = str(expected).lower()
                        break

        elif check_type == "line_spacing":
            # Search all paragraphs for one with explicit line spacing applied
            best_para = paragraph
            for p in document.paragraphs:
                if p.paragraph_format.line_spacing is not None:
                    best_para = p
                    break
            raw_ls = best_para.paragraph_format.line_spacing
            raw_rule = best_para.paragraph_format.line_spacing_rule
            # Convert EMU to pt (1 pt = 12700 EMU)
            if isinstance(raw_ls, (int, float)) and raw_ls > 100:
                actual_pt = emu_to_pt(int(raw_ls))
            elif isinstance(raw_ls, (int, float)):
                actual_pt = float(raw_ls)
            else:
                actual_pt = None
            actual = {"rule": str(raw_rule), "value_pt": round(actual_pt, 2) if actual_pt else None}
            if isinstance(expected, dict):
                exp_val = float(expected.get("value", 0))
                exp_unit = expected.get("unit", "pt")
                exp_rule = expected.get("rule", "exact")
                rule_ok = True
                if exp_rule == "exact" and raw_rule is not None:
                    rule_ok = "EXACT" in str(raw_rule).upper()
                elif exp_rule == "atLeast" and raw_rule is not None:
                    rule_ok = "LEAST" in str(raw_rule).upper()
                if exp_unit == "pt" and actual_pt is not None and exp_val > 0:
                    passed = rule_ok and compare_numeric(actual_pt, exp_val, tolerance=TOLERANCE_PT, unit="pt")
                elif exp_unit == "pt" and exp_val == 0:
                    passed = rule_ok
                elif exp_unit == "lines" and actual_pt is not None:
                    passed = rule_ok and compare_numeric(actual_pt, exp_val, tolerance=TOLERANCE_PT, unit="lines")
                else:
                    passed = False
            else:
                passed = str(raw_ls) == str(expected)

        elif check_type == "space_before":
            sb = paragraph.paragraph_format.space_before
            actual = round(sb.pt, 1) if sb else None
            if actual is not None:
                passed = compare_numeric(actual, float(expected), tolerance=TOLERANCE_PT, unit="pt")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "space_after":
            sa = paragraph.paragraph_format.space_after
            actual = round(sa.pt, 1) if sa else None
            if actual is not None:
                passed = compare_numeric(actual, float(expected), tolerance=TOLERANCE_PT, unit="pt")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "first_line_indent":
            # Search all paragraphs for one with a first line indent applied
            fi = paragraph.paragraph_format.first_line_indent
            if fi is None:
                for p in document.paragraphs:
                    if p.paragraph_format.first_line_indent is not None:
                        fi = p.paragraph_format.first_line_indent
                        break
            # Convert EMU to cm (360000 EMU = 1 cm)
            actual = emu_to_cm(int(fi)) if fi is not None else None
            if actual is not None:
                passed = compare_numeric(actual, float(expected), tolerance=TOLERANCE_CM, unit="cm")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "contains_text":
            text_to_find = expected.get("text", "") if isinstance(expected, dict) else str(expected)
            found = text_to_find.lower() in self._document_text(document, file_path).lower()
            passed = found
            actual = text_to_find if found else None

        elif check_type == "border":
            passed, actual = self._check_para_border(paragraph, expected, file_path)

        elif check_type == "shading":
            passed, actual = self._check_para_shading(paragraph, expected)

        elif check_type == "drop_cap":
            passed, actual = self._check_drop_cap(paragraph, expected)

        else:
            return CheckerResult(passed=False, details={"reason": "Unsupported paragraph formatting check."})

        return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

    def _check_font(
        self,
        document: Document,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        paragraphs = self._find_paragraphs(document, target)
        if not paragraphs:
            return CheckerResult(passed=False, details={"reason": "Font target not found."})
        locator, target_value = self._target_locator(target)
        run_text = str(target_value) if locator == "contains_text" and target_value is not None else None
        run = self._find_run(paragraphs, run_text)
        if run is None:
            return CheckerResult(passed=False, details={"reason": "No run found for font target."})

        actual = None
        actual_name = None
        theme_name = None
        if check_type == "color":
            theme_color, theme_tint, theme_shade, value = self._resolve_color_info(run, file_path)
            actual = value
            if theme_color:
                theme_name = resolve_theme_color_name(theme_color, theme_tint, theme_shade)
            passed = self._match_color(expected, actual, theme_name)
            return CheckerResult(
                passed=passed,
                actual=actual,
                details={"actual_theme": theme_name, "type": check_type},
            )
        if check_type == "size":
            actual = run.font.size.pt if run.font.size else None
            if actual is not None:
                passed = compare_numeric(actual, float(expected), tolerance=TOLERANCE_PT, unit="pt")
            else:
                passed = False
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
            theme_color, theme_tint, theme_shade, value = self._resolve_color_info(run, file_path)
            theme_name = resolve_theme_color_name(theme_color, theme_tint, theme_shade) if theme_color else None
            exp_color = expected.get("color", "") if isinstance(expected, dict) else ""
            color_ok = self._match_color(exp_color, value, theme_name)
            passed = bold_ok and color_ok
            return CheckerResult(passed=passed, actual={"bold": bold_ok, "color": value}, details={"type": check_type})
        return CheckerResult(passed=False, details={"reason": "Unsupported font check."})

    def _check_table(
        self,
        document: Document,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
    ) -> CheckerResult:
        table = self._find_table(document, target)
        if table is None:
            return CheckerResult(passed=False, details={"reason": "Table target not found."})

        if check_type == "merge_horizontal":
            row = expected.get("row")
            col_start = expected.get("col_start")
            col_end = expected.get("col_end")
            cell = self._get_table_cell(table, row, col_start)
            if cell is None:
                return CheckerResult(passed=False, details={"reason": "Merge cell not found."})
            actual_span = self._cell_grid_span(cell)
            expected_span = int(col_end - col_start + 1)
            passed = actual_span == expected_span
            return CheckerResult(
                passed=passed,
                actual=actual_span,
                details={"expected_span": expected_span, "row": row, "col_start": col_start, "col_end": col_end},
            )
        if check_type == "cell_text":
            row = expected.get("row")
            col = expected.get("col")
            expected_text = str(expected.get("text", "")).strip()
            tolerance = bool(expected.get("tolerance", False))
            cell = self._get_table_cell(table, row, col)
            if cell is None:
                return CheckerResult(passed=False, details={"reason": "Cell not found."})
            actual_text = cell.text.strip()
            passed = expected_text.lower() == actual_text.lower()
            if not passed and tolerance:
                row_text = " ".join(c.text.strip() for c in table.rows[row].cells)
                passed = expected_text.lower() in row_text.lower()
                return CheckerResult(
                    passed=passed,
                    actual=actual_text,
                    details={"type": check_type, "tolerance": tolerance, "row_text": row_text},
                )
            return CheckerResult(passed=passed, actual=actual_text, details={"type": check_type})
        if check_type == "cell_alignment":
            row = expected.get("row")
            col = expected.get("col")
            horizontal = expected.get("horizontal")
            cell = self._get_table_cell(table, row, col)
            if cell is None:
                return CheckerResult(passed=False, details={"reason": "Cell not found."})
            paragraph = cell.paragraphs[0] if cell.paragraphs else None
            actual = None
            if paragraph is not None:
                actual = ALIGNMENT_MAP.get(paragraph.alignment, "left")
            passed = actual == str(horizontal).lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        return CheckerResult(passed=False, details={"reason": "Unsupported table check."})

    def _check_document(
        self,
        document: Document,
        check_type: str,
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        section = document.sections[0]  # Assume first section
        if check_type == "paper_size":
            if isinstance(expected, str):
                if expected.upper() == "A4":
                    actual_width = section.page_width
                    actual_height = section.page_height
                    a4_width = 7560000
                    a4_height = 10692000
                    passed = abs(actual_width - a4_width) < 150000 and abs(actual_height - a4_height) < 150000
                    return CheckerResult(passed=passed, actual={"width": actual_width, "height": actual_height}, details={"type": check_type})
            return CheckerResult(passed=False, details={"reason": "Unsupported paper_size format."})
        if check_type == "orientation":
            actual = "portrait" if section.orientation == 0 else "landscape"
            passed = actual == str(expected).lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "margins":
            cm_to_emu = 360000
            actual = {
                "top": section.top_margin / cm_to_emu,
                "bottom": section.bottom_margin / cm_to_emu,
                "left": section.left_margin / cm_to_emu,
                "right": section.right_margin / cm_to_emu,
            }
            if isinstance(expected, dict):
                passed = all(abs(actual[k] - expected[k]) < 0.1 for k in expected if k in actual)
                return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
            return CheckerResult(passed=False, details={"reason": "Margins expected as dict."})
        if check_type == "page_border":
            xml = _read_docx_part(file_path, "word/document.xml")
            actual_style = "none"
            if xml:
                root = etree.fromstring(xml.encode("utf-8"))
                pg_borders = root.find(
                    ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pgBorders"
                )
                if pg_borders is not None:
                    top = pg_borders.find(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}top"
                    )
                    if top is not None:
                        val = top.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
                        if val:
                            actual_style = val.lower()
            expected_style = None
            expected_first_page = False
            if isinstance(expected, dict):
                expected_style = str(expected.get("style", "")).lower()
                expected_first_page = bool(expected.get("first_page_only", False))
            passed = expected_style == actual_style if expected_style else False
            return CheckerResult(
                passed=passed,
                actual={"style": actual_style},
                details={"type": check_type, "first_page_only": expected_first_page},
            )
        if check_type == "watermark":
            # Watermarks are stored as shapes in the header drawing XML, not as plain text
            # Check all header parts (header1, header2, header3)
            COLOUR_NAME_TO_HEX = {
                "blue": ["0070c0", "0000ff", "4472c4", "1f497d"],
                "red": ["ff0000", "c00000", "ff0000"],
                "green": ["00b050", "008000", "70ad47"],
                "yellow": ["ffff00", "ffc000"],
                "black": ["000000"],
                "white": ["ffffff"],
                "gray": ["808080", "a5a5a5"],
                "grey": ["808080", "a5a5a5"],
            }
            actual_text = ""
            actual_colour = ""
            actual_layout = ""
            for header_part in ("word/header1.xml", "word/header2.xml", "word/header3.xml"):
                wm_xml = _read_docx_part(file_path, header_part)
                if not wm_xml:
                    continue
                wm_root = etree.fromstring(wm_xml.encode("utf-8"))
                NS_V = "urn:schemas-microsoft-com:vml"
                NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
                for tp in wm_root.iter(f"{{{NS_V}}}textpath"):
                    s = tp.get("string", "")
                    if s:
                        actual_text = s
                        break
                if not actual_text:
                    for t in wm_root.iter(f"{{{NS_A}}}t"):
                        if t.text and t.text.strip():
                            actual_text += t.text.strip()
                for shape in wm_root.iter(f"{{{NS_V}}}shape"):
                    style = shape.get("style", "")
                    if "rotation" in style:
                        actual_layout = "diagonal"
                    fill_color = shape.get("fillcolor", "").lstrip("#").lower()
                    if fill_color:
                        actual_colour = fill_color
                    break
                if actual_text:
                    break
            if isinstance(expected, str):
                exp_lower = expected.lower()
                if exp_lower in ("diagonal", "horizontal"):
                    passed = actual_layout.lower() == exp_lower
                elif exp_lower in COLOUR_NAME_TO_HEX:
                    passed = actual_colour.lower() in COLOUR_NAME_TO_HEX[exp_lower]
                else:
                    passed = exp_lower in actual_text.lower()
            else:
                passed = bool(actual_text)
            return CheckerResult(
                passed=passed,
                actual={"text": actual_text, "colour": actual_colour, "layout": actual_layout},
                details={"type": check_type},
            )
        if check_type == "header_text":
            header = section.header
            actual = " ".join(p.text.strip() for p in header.paragraphs if p.text.strip()) if header else ""
            if isinstance(expected, bool):
                passed = bool(actual) == expected
            else:
                passed = str(expected).lower() in actual.lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "header_alignment":
            # Use python-docx to read header paragraph alignment directly
            actual = "left"
            for header_part in (section.header, section.even_page_header, section.first_page_header):
                try:
                    paragraphs = [p for p in header_part.paragraphs if p.text.strip()]
                    if paragraphs:
                        actual = ALIGNMENT_MAP.get(paragraphs[0].alignment, "left")
                        break
                except Exception:
                    continue
            passed = actual == str(expected).lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "footer_text":
            # Read footer XML directly from zip — python-docx section.footer may return empty linked footer
            footer_xml = _read_docx_part(file_path, "word/footer1.xml") or _read_docx_part(file_path, "word/footer2.xml")
            parts = []
            if footer_xml:
                footer_root = etree.fromstring(footer_xml.encode("utf-8"))
                WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                for t in footer_root.iter(f"{{{WNS}}}t"):
                    if t.text and t.text.strip():
                        parts.append(t.text.strip())
                for instr in footer_root.iter(f"{{{WNS}}}instrText"):
                    if instr.text and instr.text.strip():
                        parts.append(instr.text.strip())
            actual = " ".join(parts)
            if isinstance(expected, bool):
                passed = bool(actual) == expected
            elif isinstance(expected, str) and "page x of y" in expected.lower():
                has_page = any("PAGE" in p for p in parts)
                has_num = any("NUMPAGES" in p for p in parts)
                passed = has_page and has_num
            else:
                passed = str(expected).lower() in actual.lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "footer_alignment":
            # Read footer XML directly from zip
            footer_xml = _read_docx_part(file_path, "word/footer1.xml") or _read_docx_part(file_path, "word/footer2.xml")
            actual = "left"
            if footer_xml:
                footer_root = etree.fromstring(footer_xml.encode("utf-8"))
                WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                jc = footer_root.find(f".//{{{WNS}}}jc")
                if jc is not None:
                    actual = jc.get(f"{{{WNS}}}val", "left").lower()
            passed = actual == str(expected).lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "hyphenation":
            # Read from word/settings.xml — <w:autoHyphenation w:val="1"/>
            settings_xml = _read_docx_part(file_path, "word/settings.xml")
            passed = False
            if settings_xml:
                settings_root = etree.fromstring(settings_xml.encode("utf-8"))
                auto_hyph = settings_root.find(
                    ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}autoHyphenation"
                )
                if auto_hyph is not None:
                    val = auto_hyph.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
                    passed = val not in ("0", "false")
            return CheckerResult(passed=passed, actual=passed, details={"type": check_type})

        if check_type == "contains_date":
            date_pattern = re.compile(
                r"(\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b)|"
                r"(\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b)|"
                r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{4}\b)|"
                r"(\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b)",
                re.IGNORECASE,
            )
            found = bool(date_pattern.search(self._document_text(document, file_path)))
            return CheckerResult(passed=found, actual={"contains_date": found}, details={"type": check_type})

        return CheckerResult(passed=False, details={"reason": "Unsupported document check."})

    def _check_style_applied(
        self,
        document: Document,
        target: Dict[str, Any],
        expected: Any,
    ) -> CheckerResult:
        """Check that a paragraph has a specific style applied."""
        exp_style = ""
        if isinstance(expected, dict):
            exp_style = expected.get("style", "").lower()
        else:
            exp_style = str(expected).lower()

        paragraphs = self._find_paragraphs(document, target)
        if not paragraphs:
            # Scan all paragraphs for the style
            paragraphs = document.paragraphs

        for p in paragraphs:
            if p.style and exp_style in p.style.name.lower():
                return CheckerResult(passed=True, actual=p.style.name, details={"type": "style_applied"})
        return CheckerResult(passed=False, actual=None, details={"type": "style_applied", "reason": f"Style '{exp_style}' not found."})

    def _check_object(
        self,
        document: Document,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        """Handle object-domain checks (images and SmartArt) using raw Word XML."""
        WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
        NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
        NS_DGM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
        ns = {"a": NS_A, "pic": NS_PIC, "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"}

        doc_xml = _read_docx_part(file_path, "word/document.xml")
        if not doc_xml:
            return CheckerResult(passed=False, details={"reason": "Document XML not readable."})
        root = etree.fromstring(doc_xml.encode("utf-8"))
        pictures = root.xpath(".//pic:pic", namespaces=ns)

        def picture_extent_cm(pic) -> Optional[float]:
            extents = pic.xpath("ancestor::*[local-name()='inline' or local-name()='anchor'][1]/*[local-name()='extent'][1]")
            if not extents:
                return None
            cx = extents[0].get("cx")
            return round(int(cx) / 360000.0, 2) if cx else None

        if check_type == "image_width":
            exp_cm = float(expected.get("width_cm", 5.0)) if isinstance(expected, dict) else 5.0
            widths = [width for width in (picture_extent_cm(pic) for pic in pictures) if width is not None]
            closest = min(widths, key=lambda width: abs(width - exp_cm)) if widths else None
            passed = any(abs(width - exp_cm) < 0.3 for width in widths)
            return CheckerResult(passed=passed, actual=closest, details={"type": check_type, "widths_cm": widths})

        if check_type == "smartart":
            # Check for presence AND optionally match SmartArt layout/type.
            dg_data = root.findall(f".//{{{NS_DGM}}}relIds")
            rels_xml = _read_docx_part(file_path, "word/_rels/document.xml.rels")
            has_smartart = bool(dg_data)
            if not has_smartart and rels_xml:
                has_smartart = "diagram" in rels_xml.lower()

            # If no SmartArt at all, fail.
            if not has_smartart:
                return CheckerResult(passed=False, actual={"found": False}, details={"type": check_type})

            # If expected includes a type, attempt to extract diagram kind.
            # SmartArt "type" typically appears in diagram XML as a layout name.
            # We use heuristic matching against diagram parts.
            if isinstance(expected, dict) and expected.get("type"):
                exp_type = str(expected.get("type")).lower()

                found_any = False
                matched_any = False

                # Search all diagramData / diagram parts.
                for part in self._relationship_targets(file_path, "diagramData"):
                    xml = _read_docx_part(file_path, part)
                    if not xml:
                        continue
                    try:
                        droot = etree.fromstring(xml.encode("utf-8"))
                    except Exception:
                        continue

                    found_any = True
                    # Common containers: a:sp or diagram elements with attributes.
                    # We extract any attributes/names that look like a layout/type.
                    text_blob = []
                    # Collect text nodes.
                    for n in droot.iter():
                        if n.text and n.text.strip():
                            text_blob.append(n.text.strip())
                    blob = " ".join(text_blob).lower()

                    # Heuristic: match expected type anywhere in diagram data text.
                    if exp_type in blob:
                        matched_any = True
                        break

                # If we couldn’t inspect diagramData parts, fall back to presence-only.
                passed = matched_any if found_any else has_smartart
                return CheckerResult(
                    passed=passed,
                    actual={"found": has_smartart, "matched_type": matched_any if found_any else None, "expected_type": exp_type},
                    details={"type": check_type},
                )

            # Presence-only if no type was provided.
            return CheckerResult(passed=True, actual={"found": True}, details={"type": check_type})

        if check_type == "smartart_text":
            contains = expected.get("contains", "") if isinstance(expected, dict) else str(expected)
            expected_terms = [term.strip().lower() for term in re.split(r"[,;]", contains) if term.strip()]
            diagram_text = self._diagram_text(file_path)
            lower_text = diagram_text.lower()
            found_text = all(term in lower_text for term in expected_terms) if expected_terms else bool(diagram_text)
            return CheckerResult(
                passed=found_text,
                actual={"text": diagram_text, "searched_for": contains},
                details={"type": check_type},
            )

        if check_type == "smartart_color":
            scheme = expected.get("scheme", "colorful") if isinstance(expected, dict) else str(expected)
            found_colorful = self._diagram_color_scheme(file_path).lower() == str(scheme).lower()
            return CheckerResult(passed=found_colorful, actual={"colorful": found_colorful}, details={"type": check_type})

        if check_type == "image_crop":
            expected_shape = expected.get("shape", "oval") if isinstance(expected, dict) else str(expected)
            expected_prst = {"oval": "ellipse", "circle": "ellipse"}.get(str(expected_shape).lower(), str(expected_shape).lower())
            shapes = [
                geom.get("prst", "").lower()
                for pic in pictures
                for geom in pic.xpath(".//pic:spPr/a:prstGeom", namespaces=ns)
            ]
            passed = expected_prst in shapes
            return CheckerResult(passed=passed, actual={"shapes": shapes}, details={"type": check_type})

        if check_type == "image_border":
            expected_width = float(expected.get("width_pt", 0)) if isinstance(expected, dict) and expected.get("width_pt") is not None else None
            expected_color = expected.get("color") if isinstance(expected, dict) else None
            borders = []
            for pic in pictures:
                for line in pic.xpath(".//pic:spPr/a:ln", namespaces=ns):
                    width_pt = round(int(line.get("w", "0")) / 12700.0, 2)
                    color = None
                    srgb = line.find(".//a:srgbClr", namespaces=ns)
                    scheme = line.find(".//a:schemeClr", namespaces=ns)
                    if srgb is not None:
                        color = srgb.get("val", "").upper()
                    elif scheme is not None:
                        color = scheme.get("val", "")
                    borders.append({"width_pt": width_pt, "color": color})
            passed = bool(borders)
            if expected_width is not None:
                passed = passed and any(abs(border["width_pt"] - expected_width) < 0.2 for border in borders)
            if expected_color:
                passed = passed and any(self._match_color(expected_color, border["color"], border["color"]) for border in borders)
            return CheckerResult(passed=passed, actual={"borders": borders}, details={"type": check_type})

        return CheckerResult(passed=False, details={"reason": f"Unsupported object check type '{check_type}'."})

    def _relationship_targets(self, file_path: Path, type_fragment: str) -> List[str]:
        rels_xml = _read_docx_part(file_path, "word/_rels/document.xml.rels")
        if not rels_xml:
            return []
        try:
            root = etree.fromstring(rels_xml.encode("utf-8"))
        except Exception:
            return []
        targets = []
        for rel in root:
            rel_type = rel.get("Type", "")
            target = rel.get("Target", "")
            if type_fragment.lower() in rel_type.lower() and target:
                targets.append(target if target.startswith("word/") else f"word/{target.lstrip('../')}")
        return targets

    def _diagram_text(self, file_path: Path) -> str:
        parts = []
        for part in self._relationship_targets(file_path, "diagramData"):
            xml = _read_docx_part(file_path, part)
            if not xml:
                continue
            try:
                root = etree.fromstring(xml.encode("utf-8"))
            except Exception:
                continue
            for node in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"):
                if node.text:
                    parts.append(node.text)
        return " ".join(parts)

    def _diagram_color_scheme(self, file_path: Path) -> str:
        for part in self._relationship_targets(file_path, "diagramColors"):
            xml = _read_docx_part(file_path, part)
            if not xml:
                continue
            try:
                root = etree.fromstring(xml.encode("utf-8"))
            except Exception:
                continue
            for node in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/diagram}cat"):
                scheme = node.get("type")
                if scheme:
                    return scheme
        return ""

    def check(
        self,
        domain: str,
        check_type: str,
        target: Dict[str, Any],
        expected: Any,
        file_path: Path,
    ) -> CheckerResult:
        document = self._load_document(file_path)
        if domain == "paragraph_formatting":
            return self._check_paragraph_formatting(document, check_type, target, expected, file_path)
        if domain == "font":
            return self._check_font(document, check_type, target, expected, file_path)
        if domain == "table":
            return self._check_table(document, check_type, target, expected)
        if domain == "list":
            return self._check_list(document, check_type, target, expected)
        if domain == "advanced" and check_type == "bookmark":
            return self._check_bookmark(file_path, expected)
        if domain == "advanced" and check_type == "bibliography":
            return self._check_bibliography(file_path, expected)
        if domain == "advanced" and check_type == "style_applied":
            return self._check_style_applied(document, target, expected)
        if domain == "object":
            return self._check_object(document, check_type, target, expected, file_path)
        if domain == "document":
            return self._check_document(document, check_type, expected, file_path)
        if domain == "paragraph_formatting" and check_type in ("header_alignment", "footer_alignment"):
            return self._check_document(document, check_type, expected, file_path)
        return CheckerResult(passed=False, details={"reason": f"Unsupported domain '{domain}'."})
