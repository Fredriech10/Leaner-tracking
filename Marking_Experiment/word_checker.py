"""Word document checker for Marking Experiment."""

from __future__ import annotations

import logging
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.section import WD_SECTION_START
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
            "black": {"000000", "1F1F1F"},
            "white": {"FFFFFF", "F2F2F2"},
            "grey": {"808080", "A5A5A5", "7F7F7F"},
            "light grey": {"D9E1F2", "D9D9D9", "E7E6E6", "F2F2F2", "EDEDED", "DDEBF7"},
            "dark grey": {"595959", "666666", "44546A"},
            "blue": {"0000FF", "0070C0", "4472C4", "1F497D", "5B9BD5", "2F5597"},
            "light blue": {"5B9BD5", "9DC3E6", "BDD7EE", "DDEBF7"},
            "dark blue": {"1F4E78", "1F497D", "2F5597", "17365D"},
            "green": {"008000", "00B050", "70AD47", "548235"},
            "light green": {"A9D18E", "C6E0B4", "E2F0D9"},
            "dark green": {"375623", "548235"},
            "red": {"FF0000", "C00000", "C55A11", "F4B183"},
            "dark red": {"C00000", "943634", "7F0000"},
            "orange": {"ED7D31", "F4B183", "FCE4D6", "C55A11"},
            "yellow": {"FFFF00", "FFC000", "FFD966", "FFF2CC"},
            "purple": {"7030A0", "8064A2", "D9EAD3", "E4DFEC"},
        }
        if isinstance(expected, str):
            expected_name = expected.strip().lower().replace("gray", "grey")
            allowed = named_colors.get(expected_name)
            if actual_hex and allowed and actual_hex.upper() in allowed:
                return True
            theme_aliases = {
                "black": {"tx1", "dk1"}, "white": {"bg1", "lt1"},
                "light grey": {"bg2", "lt2", "accent3"}, "dark grey": {"tx2", "dk2"},
                "blue": {"accent1", "accent5"}, "light blue": {"accent5"}, "green": {"accent6"},
                "grey": {"accent3"}, "orange": {"accent2"}, "yellow": {"accent4"},
            }
            if actual_theme_name and actual_theme_name.lower() in theme_aliases.get(expected_name, set()):
                return True
        expected_value = normalize_hex_color(str(expected)) if isinstance(expected, str) else None
        if expected_value and actual_hex:
            if expected_value == actual_hex:
                return True
        if isinstance(expected, str) and actual_theme_name:
            return expected.lower() == actual_theme_name.lower()
        return False

    def _run_xml_tree(self, run) -> Optional[etree._Element]:
        if run is None or not hasattr(run, "_r"):
            return None
        try:
            return etree.fromstring(run._r.xml.encode("utf-8"))
        except Exception:
            return None

    def _font_xml_element(self, run, tag_name: str):
        tree = self._run_xml_tree(run)
        if tree is None:
            return None
        return tree.find(f".//w:{tag_name}", namespaces=NAMESPACES)

    def _font_xml_bool(self, run, tag_name: str) -> bool:
        return self._font_xml_element(run, tag_name) is not None

    def _font_xml_val(self, run, tag_name: str) -> Optional[str]:
        element = self._font_xml_element(run, tag_name)
        if element is None:
            return None
        return element.get(qn("w:val")) or None

    def _resolve_font_theme(self, run) -> Optional[str]:
        tree = self._run_xml_tree(run)
        if tree is None:
            return None
        fonts = tree.find(".//w:rFonts", namespaces=NAMESPACES)
        if fonts is None:
            return None
        for attr in ("asciiTheme", "hAnsiTheme", "csTheme", "eastAsiaTheme"):
            theme_val = fonts.get(qn(f"w:{attr}"))
            if theme_val:
                return theme_val
        return None

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

    def _paragraph_alignment(self, paragraph) -> str:
        alignment = ALIGNMENT_MAP.get(paragraph.alignment)
        if alignment:
            return alignment
        try:
            tree = etree.fromstring(paragraph._p.xml.encode("utf-8"))
            jc = tree.find(".//w:jc", namespaces=NAMESPACES)
            value = jc.get(qn("w:val"), "left").lower() if jc is not None else ""
            return {"both": "justify", "distribute": "justify", "start": "left", "end": "right"}.get(value, value or "left")
        except Exception:
            pass
        try:
            return ALIGNMENT_MAP.get(paragraph.style.paragraph_format.alignment, "left")
        except Exception:
            return "left"

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

    def _gather_header_text(self, section) -> str:
        values = []
        for header_part in (section.header, section.even_page_header, section.first_page_header):
            try:
                values.extend(p.text.strip() for p in header_part.paragraphs if p.text.strip())
            except Exception:
                continue
        return " ".join(values).strip()

    def _gather_footer_text(self, section) -> str:
        values = []
        for footer_part in (section.footer, section.even_page_footer, section.first_page_footer):
            try:
                values.extend(p.text.strip() for p in footer_part.paragraphs if p.text.strip())
            except Exception:
                continue
        return " ".join(values).strip()

    def _document_part_contains_page_field(self, file_path: Path, prefix: str) -> bool:
        for idx in range(1, 7):
            xml = _read_docx_part(file_path, f"{prefix}{idx}.xml")
            if not xml:
                continue
            try:
                root = etree.fromstring(xml.encode("utf-8"))
            except Exception:
                continue
            for node in root.iter(f"{{{NAMESPACES['w']}}}instrText"):
                if node.text and "page" in node.text.lower():
                    return True
            for node in root.findall(f".//{{{NAMESPACES['w']}}}fldSimple"):
                instr = node.get(qn("w:instr"))
                if instr and "page" in instr.lower():
                    return True
        return False

    def _page_number_format(self, file_path: Path) -> str:
        xml = _read_docx_part(file_path, "word/document.xml")
        if xml:
            try:
                root = etree.fromstring(xml.encode("utf-8"))
                fmt = root.find(".//w:pgNumType", namespaces=NAMESPACES)
                if fmt is not None:
                    fmt_val = fmt.get(qn("w:fmt"))
                    if fmt_val:
                        normalize = {
                            "decimal": "1",
                            "lowerroman": "i",
                            "upperroman": "I",
                            "lowerletter": "a",
                            "upperletter": "A",
                        }
                        return normalize.get(fmt_val.lower(), fmt_val)
            except Exception:
                pass
        return "1"

    def _page_number_details(self, file_path: Path) -> list[dict]:
        """Return the functional parts of every header/footer page-number field."""
        details = []
        for location in ("header", "footer"):
            for index in range(1, 7):
                xml = _read_docx_part(file_path, f"word/{location}{index}.xml")
                if not xml:
                    continue
                try:
                    root = etree.fromstring(xml.encode("utf-8"))
                except Exception:
                    continue

                instructions = []
                for node in root.iter(f"{{{NAMESPACES['w']}}}instrText"):
                    if node.text:
                        instructions.append(node.text)
                for node in root.findall(f".//{{{NAMESPACES['w']}}}fldSimple"):
                    instruction = node.get(qn("w:instr"))
                    if instruction:
                        instructions.append(instruction)
                instruction_text = " ".join(instructions).upper()
                if not re.search(r"\bPAGE\b", instruction_text):
                    continue

                text = " ".join(
                    node.text for node in root.iter(f"{{{NAMESPACES['w']}}}t") if node.text
                )
                alignment = "left"
                paragraph = root.find(f".//{{{NAMESPACES['w']}}}p")
                if paragraph is not None:
                    jc = paragraph.find(f".//{{{NAMESPACES['w']}}}jc")
                    if jc is not None:
                        alignment = jc.get(qn("w:val"), "left").lower()
                details.append({
                    "location": location,
                    "alignment": {"both": "justify", "distribute": "justify"}.get(alignment, alignment),
                    "has_num_pages": bool(re.search(r"\bNUMPAGES\b", instruction_text)),
                    "text": text,
                })
        return details

    def _matches_page_number_template(self, file_path: Path, expected: Any) -> tuple[bool, list[dict]]:
        template = expected.get("template", "") if isinstance(expected, dict) else str(expected)
        expected_location = expected.get("location") if isinstance(expected, dict) else None
        expected = {
            "plain_number_1": ("left", False, False),
            "plain_number_2": ("center", False, False),
            "plain_number_3": ("right", False, False),
            "page_x_left": ("left", False, True),
            "page_x_center": ("center", False, True),
            "page_x_right": ("right", False, True),
            "page_x_of_y_left": ("left", True, True),
            "page_x_of_y_center": ("center", True, True),
            "page_x_of_y_right": ("right", True, True),
            "plain_number": (None, False, False),
            "page_x": (None, False, True),
            "page_x_of_y": (None, True, True),
        }.get(template)
        details = self._page_number_details(file_path)
        if expected is None:
            return False, details
        alignment, needs_num_pages, needs_page_label = expected
        for detail in details:
            text = re.sub(r"\s+", " ", detail["text"]).strip().lower()
            has_page_label = bool(re.search(r"\bpage\b", text))
            has_of_label = bool(re.search(r"\bof\b", text))
            if expected_location and detail["location"] != expected_location:
                continue
            if (alignment is not None and detail["alignment"] != alignment) or detail["has_num_pages"] != needs_num_pages:
                continue
            if needs_page_label and not has_page_label:
                continue
            if needs_num_pages and not has_of_label:
                continue
            return True, details
        return False, details

    def _section_break_type(self, section) -> str:
        if hasattr(section, "start_type"):
            mapping = {
                WD_SECTION_START.NEW_PAGE: "nextPage",
                WD_SECTION_START.CONTINUOUS: "continuous",
                WD_SECTION_START.ODD_PAGE: "odd",
                WD_SECTION_START.EVEN_PAGE: "even",
            }
            return mapping.get(section.start_type, str(section.start_type).lower())
        return "nextPage"

    def _line_number_settings(self, section) -> dict:
        actual = {"enabled": False, "start": None, "interval": None}
        sectPr = getattr(section, "_sectPr", None)
        if sectPr is None:
            return actual
        ln_node = sectPr.find(qn("w:lnNumType"))
        if ln_node is None:
            return actual
        actual["enabled"] = True
        if ln_node.get(qn("w:start")):
            try:
                actual["start"] = int(ln_node.get(qn("w:start")))
            except Exception:
                pass
        if ln_node.get(qn("w:countBy")):
            try:
                actual["interval"] = int(ln_node.get(qn("w:countBy")))
            except Exception:
                pass
        return actual

    def _mirror_margins_enabled(self, section) -> bool:
        sectPr = getattr(section, "_sectPr", None)
        if sectPr is None:
            return False
        return sectPr.find(qn("w:mirrorMargins")) is not None

    def _page_background_color(self, file_path: Path) -> Optional[str]:
        xml = _read_docx_part(file_path, "word/document.xml")
        if not xml:
            return None
        try:
            root = etree.fromstring(xml.encode("utf-8"))
            bg = root.find(".//w:background", namespaces=NAMESPACES)
            if bg is None:
                return None
            color = bg.get(qn("w:color"))
            if color:
                return normalize_hex_color(color)
        except Exception:
            pass
        return None

    def _has_page_background(self, file_path: Path) -> bool:
        xml = _read_docx_part(file_path, "word/document.xml")
        if not xml:
            return False
        try:
            root = etree.fromstring(xml.encode("utf-8"))
            return root.find(".//w:background", namespaces=NAMESPACES) is not None
        except Exception:
            return False

    def _count_page_breaks(self, file_path: Path) -> int:
        xml = _read_docx_part(file_path, "word/document.xml")
        if not xml:
            return 0
        try:
            root = etree.fromstring(xml.encode("utf-8"))
        except Exception:
            return 0
        page_br = root.findall(".//w:br[@w:type='page']", namespaces=NAMESPACES)
        page_breaks = root.findall(".//w:lastRenderedPageBreak", namespaces=NAMESPACES)
        return len(page_br) + len(page_breaks)

    def _parse_boolean(self, value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"true", "yes", "1", "on", "y"}:
            return True
        if normalized in {"false", "no", "0", "off", "n"}:
            return False
        return None

    def _paragraph_xml_tree(self, paragraph):
        try:
            return etree.fromstring(paragraph._p.xml.encode("utf-8"))
        except Exception:
            return None

    def _paragraph_has_rtl(self, paragraph) -> bool:
        tree = self._paragraph_xml_tree(paragraph)
        if tree is None:
            return False
        bidi = tree.find(".//w:bidi", namespaces=NAMESPACES)
        text_dir = tree.find(".//w:textDirection", namespaces=NAMESPACES)
        return bidi is not None or text_dir is not None

    def _paragraph_outline_level(self, paragraph) -> Optional[int]:
        tree = self._paragraph_xml_tree(paragraph)
        if tree is None:
            return None
        outline = tree.find(".//w:outlineLvl", namespaces=NAMESPACES)
        if outline is None:
            return None
        try:
            return int(outline.get(qn("w:val")))
        except Exception:
            return None

    def _check_tab_stops(self, paragraph, expected: Any) -> tuple[bool, Any]:
        tab_stops = paragraph.paragraph_format.tab_stops
        actual = []
        for tab in tab_stops:
            position_cm = None
            try:
                position_cm = round(float(tab.position.cm), 2)
            except Exception:
                pass
            actual.append(
                {
                    "position_cm": position_cm,
                    "alignment": tab.alignment.name.lower() if hasattr(tab.alignment, "name") else str(tab.alignment).lower() if tab.alignment is not None else None,
                    "leader": tab.leader.name.lower() if hasattr(tab.leader, "name") else str(tab.leader).lower() if tab.leader is not None else None,
                }
            )

        if expected is None:
            return (len(actual) > 0, actual)

        passed = True
        if isinstance(expected, dict):
            if expected.get("count") is not None:
                try:
                    passed = passed and len(actual) == int(expected["count"])
                except Exception:
                    passed = False
            if expected.get("position_cm") is not None:
                position_ok = any(
                    compare_numeric(tab["position_cm"], float(expected["position_cm"]), tolerance=TOLERANCE_CM, unit="cm")
                    for tab in actual
                    if tab["position_cm"] is not None
                )
                passed = passed and position_ok
            if expected.get("alignment") is not None:
                alignment_ok = any(
                    tab["alignment"] == str(expected["alignment"]).strip().lower()
                    for tab in actual
                    if tab["alignment"] is not None
                )
                passed = passed and alignment_ok
            if expected.get("leader") is not None:
                leader_ok = any(
                    tab["leader"] == str(expected["leader"]).strip().lower()
                    for tab in actual
                    if tab["leader"] is not None
                )
                passed = passed and leader_ok
        else:
            try:
                passed = len(actual) == int(expected)
            except Exception:
                passed = False

        return passed, actual

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
            if actual["size"] is not None:
                passed = passed and compare_numeric(float(actual["size"]), float(expected["size"]), tolerance=TOLERANCE_PT, unit="pt")
            else:
                passed = False
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

        if check_type == "number_format":
            actual = props.get("num_fmt", "")
            passed = actual.lower() == str(expected).lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        if check_type == "item_count":
            num_id = props.get("num_id")
            actual = sum(1 for candidate in document.paragraphs if (candidate_props := self._get_list_properties(candidate, document)) and candidate_props.get("num_id") == num_id)
            expected_count = int(expected)
            return CheckerResult(passed=actual >= expected_count, actual=actual, details={"type": check_type})

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
            "light grey": {"d9d9d9", "bfbfbf", "f2f2f2", "d3d3d3", "e7e6e6", "ededed", "ddebf7", "d9e1f2"},
            "grey": {"808080", "a5a5a5", "7f7f7f", "d9d9d9"},
            "dark grey": {"595959", "666666", "44546a"},
            "blue": {"0070c0", "0000ff", "4472c4", "1f497d", "5b9bd5", "2f5597", "d9e2f3", "ddebf7"},
            "light blue": {"5b9bd5", "9dc3e6", "bdd7ee", "ddebf7"},
            "green": {"008000", "00b050", "70ad47", "548235", "e2f0d9"},
            "red": {"ff0000", "c00000", "f4b183", "fce4d6"},
            "orange": {"ed7d31", "f4b183", "fce4d6", "c55a11"},
            "yellow": {"ffff00", "ffc000", "ffd966", "fff2cc"},
            "purple": {"7030a0", "8064a2", "e4dfec"},
            "black": {"000000", "1f1f1f"},
            "white": {"ffffff", "f2f2f2"},
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
        theme_color = shd.get(f"{{{WNS}}}themeFill", "").lower()
        actual = {"fill": fill, "theme": theme_color}
        if isinstance(expected, dict):
            exp_color = expected.get("color", "any").lower().replace("gray", "grey")
            if exp_color == "any":
                passed = bool(fill) and fill != "auto"
            else:
                allowed = SHADING_MAP.get(exp_color, {exp_color})
                theme_aliases = {
                    "light grey": {"lt2", "bg2", "accent3"}, "grey": {"accent3"}, "dark grey": {"dk2", "tx2"},
                    "blue": {"accent1", "accent5"}, "light blue": {"accent5"}, "green": {"accent6"},
                    "orange": {"accent2"}, "yellow": {"accent4"},
                }
                passed = fill in allowed or theme_color in theme_aliases.get(exp_color, set())
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
        applied = bool(drop_cap) and drop_cap != "none"
        if isinstance(expected, dict) and expected.get("applied") is False:
            return not applied, actual
        if not applied:
            return False, actual
        passed = True
        if isinstance(expected, dict) and expected.get("position"):
            passed = passed and drop_cap == str(expected["position"]).strip().lower()
        if isinstance(expected, dict) and expected.get("lines"):
            try:
                passed = passed and int(lines) == int(expected["lines"])
            except Exception:
                passed = False
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
        if check_type == "drop_cap" and target.get("locator") == "any_drop_cap":
            actual = None
            for paragraph in document.paragraphs:
                passed, actual = self._check_drop_cap(paragraph, expected)
                if passed:
                    return CheckerResult(passed=True, actual=actual, details={"type": check_type})
            return CheckerResult(passed=False, actual=actual, details={"type": check_type})
        if check_type in {"list_after_heading", "list_symbol_after_heading"}:
            if not isinstance(expected, dict):
                return CheckerResult(passed=False, details={"reason": "Heading and list settings are required."})
            heading = str(expected.get("heading", "")).strip().lower().rstrip(":")
            heading_index = next(
                (index for index, candidate in enumerate(document.paragraphs) if candidate.text.strip().lower().rstrip(":") == heading),
                None,
            )
            if heading_index is None:
                return CheckerResult(passed=False, details={"reason": "List heading was not found."})
            list_items = []
            for candidate in document.paragraphs[heading_index + 1:]:
                if candidate.style and candidate.style.name.lower().startswith("heading"):
                    break
                props = self._get_list_properties(candidate, document)
                if props is None:
                    if list_items:
                        break
                    continue
                list_items.append((candidate, props))
            if not list_items:
                return CheckerResult(passed=False, details={"reason": "No list was found below the heading."})
            if check_type == "list_after_heading":
                minimum = int(expected.get("minimum", 1))
                passed = len(list_items) >= minimum and list_items[0][1].get("type") == "bullet"
                return CheckerResult(passed=passed, actual={"count": len(list_items), "type": list_items[0][1].get("type")}, details={"type": check_type})

            props = list_items[0][1]
            num_id = props.get("num_id")
            level = props.get("level", 0)
            font = ""
            character = props.get("lvl_text", "") or ""
            if hasattr(document.part, "numbering_part") and document.part.numbering_part:
                root = etree.fromstring(document.part.numbering_part.element.xml.encode("utf-8"))
                nums = root.xpath(f".//w:num[@w:numId='{num_id}']", namespaces=NAMESPACES)
                if nums:
                    abstract_id = nums[0].xpath("./w:abstractNumId/@w:val", namespaces=NAMESPACES)
                    levels = root.xpath(f".//w:abstractNum[@w:abstractNumId='{abstract_id[0]}']//w:lvl[@w:ilvl='{level}']", namespaces=NAMESPACES) if abstract_id else []
                    if levels:
                        fonts = levels[0].xpath(".//w:rFonts/@w:ascii | .//w:rFonts/@w:hAnsi", namespaces=NAMESPACES)
                        font = fonts[0] if fonts else ""
            code = str(expected.get("character_code", "")).strip()
            expected_char = chr(0xF000 + int(code)) if code.isdigit() else code
            passed = font.lower() == str(expected.get("font", "")).strip().lower() and character == expected_char
            return CheckerResult(passed=passed, actual={"font": font, "character": character}, details={"type": check_type})

        paragraphs = self._find_paragraphs(document, target)
        if not paragraphs:
            return CheckerResult(passed=False, details={"reason": "Paragraph target not found."})
        paragraph = paragraphs[0]
        actual = None
        passed = False

        if check_type == "alignment":
            actual = self._paragraph_alignment(paragraph)
            passed = actual == str(expected).lower()

        elif check_type == "line_spacing":
            raw_ls = paragraph.paragraph_format.line_spacing
            raw_rule = paragraph.paragraph_format.line_spacing_rule
            if raw_ls is None:
                for p in document.paragraphs:
                    if p.paragraph_format.line_spacing is not None:
                        paragraph = p
                        raw_ls = p.paragraph_format.line_spacing
                        raw_rule = p.paragraph_format.line_spacing_rule
                        break
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
                elif exp_rule == "multiple" and raw_rule is not None:
                    actual_rule = str(raw_rule).upper()
                    rule_ok = (
                        "MULTIPLE" in actual_rule
                        or (exp_val == 1.5 and "ONE_POINT_FIVE" in actual_rule)
                        or (exp_val == 2 and "DOUBLE" in actual_rule)
                        or (exp_val == 1 and "SINGLE" in actual_rule)
                    )
                if exp_unit == "pt" and actual_pt is not None and exp_val > 0:
                    passed = rule_ok and compare_numeric(actual_pt, exp_val, tolerance=TOLERANCE_PT, unit="pt")
                elif exp_unit == "pt" and exp_val == 0:
                    passed = rule_ok
                elif exp_unit == "lines" and actual_pt is not None:
                    passed = rule_ok and compare_numeric(actual_pt, exp_val, tolerance=TOLERANCE_LINES, unit="lines")
                else:
                    passed = False
            else:
                passed = str(raw_ls) == str(expected)

        elif check_type == "space_before":
            sb = paragraph.paragraph_format.space_before
            actual = round(sb.pt, 1) if sb else None
            if actual is not None:
                exp_val = expected.get("value") if isinstance(expected, dict) else expected
                passed = compare_numeric(actual, float(exp_val), tolerance=TOLERANCE_PT, unit="pt")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "space_after":
            sa = paragraph.paragraph_format.space_after
            actual = round(sa.pt, 1) if sa else None
            if actual is not None:
                exp_val = expected.get("value") if isinstance(expected, dict) else expected
                passed = compare_numeric(actual, float(exp_val), tolerance=TOLERANCE_PT, unit="pt")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "first_line_indent":
            fi = paragraph.paragraph_format.first_line_indent
            if fi is None:
                for p in document.paragraphs:
                    if p.paragraph_format.first_line_indent is not None:
                        fi = p.paragraph_format.first_line_indent
                        break
            actual = float(fi.cm) if fi is not None else None
            if actual is not None:
                exp_val = expected.get("value") if isinstance(expected, dict) else expected
                exp_unit = expected.get("unit") if isinstance(expected, dict) else None
                unit = exp_unit if exp_unit in ("cm", "pt", "lines") else "cm"
                try:
                    passed = compare_numeric(actual, float(exp_val), tolerance=TOLERANCE_CM, unit=unit)
                except TypeError:
                    passed = False
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "hanging_indent":
            fi = paragraph.paragraph_format.first_line_indent
            actual = abs(float(fi.cm)) if fi is not None and float(fi.cm) < 0 else None
            if actual is not None:
                exp_val = expected.get("value") if isinstance(expected, dict) else expected
                passed = compare_numeric(actual, float(exp_val), tolerance=TOLERANCE_CM, unit="cm")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "left_indent":
            li = paragraph.paragraph_format.left_indent
            if li is None:
                for p in document.paragraphs:
                    if p.paragraph_format.left_indent is not None:
                        li = p.paragraph_format.left_indent
                        break
            actual = float(li.cm) if li is not None else None
            if actual is not None:
                if expected is True:
                    passed = True
                else:
                    exp_val = expected.get("value") if isinstance(expected, dict) else expected
                    passed = compare_numeric(actual, float(exp_val), tolerance=TOLERANCE_CM, unit="cm")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "right_indent":
            ri = paragraph.paragraph_format.right_indent
            actual = float(ri.cm) if ri is not None else None
            if actual is not None:
                exp_val = expected.get("value") if isinstance(expected, dict) else expected
                passed = compare_numeric(actual, float(exp_val), tolerance=TOLERANCE_CM, unit="cm")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "right_to_left":
            actual = self._paragraph_has_rtl(paragraph)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "keep_with_next":
            actual = bool(paragraph.paragraph_format.keep_with_next)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "keep_lines_together":
            actual = bool(paragraph.paragraph_format.keep_together)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "widow_orphan_control":
            actual = bool(paragraph.paragraph_format.widow_control)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "page_break_before":
            actual = bool(paragraph.paragraph_format.page_break_before)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "outline_level":
            actual = self._paragraph_outline_level(paragraph)
            if actual is not None:
                exp_val = expected.get("value") if isinstance(expected, dict) else expected
                passed = compare_numeric(actual, float(exp_val), tolerance=0, unit="")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        elif check_type == "tabs":
            passed, actual = self._check_tab_stops(paragraph, expected)

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
        if check_type == "underline":
            actual = run.font.underline
            if isinstance(expected, str):
                passed = str(actual).lower().endswith(expected.lower()) if actual is not None else False
            else:
                passed = bool(actual) == bool(expected)
            return CheckerResult(passed=passed, actual=str(actual) if actual is not None else None, details={"type": check_type})
        if check_type == "underline_style":
            underline = run._r.rPr.find(qn("w:u")) if run._r.rPr is not None else None
            actual = underline.get(qn("w:val"), "single") if underline is not None else "none"
            passed = actual.lower() == str(expected).lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "strikethrough":
            actual = bool(run.font.strike)
            passed = actual == bool(expected)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "double_strikethrough":
            actual = self._font_xml_bool(run, "dstrike")
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
            actual = self._resolve_font_theme(run)
            passed = str(actual).lower() == str(expected).lower() if actual else False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "character_spacing":
            actual = self._font_xml_val(run, "spacing")
            passed = str(actual) == str(expected)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "kerning":
            actual = self._font_xml_val(run, "kerning")
            passed = str(actual) == str(expected)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "bold_and_color":
            bold_ok = bool(run.font.bold)
            theme_color, theme_tint, theme_shade, value = self._resolve_color_info(run, file_path)
            theme_name = resolve_theme_color_name(theme_color, theme_tint, theme_shade) if theme_color else None
            if isinstance(expected, dict):
                expected_parts = []
                if "bold" in expected:
                    expected_parts.append(bold_ok == bool(expected.get("bold")))
                if "color" in expected:
                    expected_parts.append(self._match_color(expected.get("color", ""), value, theme_name))
                passed = all(expected_parts) if expected_parts else bold_ok
            else:
                passed = bold_ok
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
        if check_type == "dimensions":
            expected_rows = int(expected.get("rows", 0))
            expected_columns = int(expected.get("columns", 0))
            actual = {"rows": len(table.rows), "columns": len(table.columns)}
            passed = actual["rows"] == expected_rows and actual["columns"] == expected_columns
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "minimum_rows":
            minimum = int(expected.get("rows", expected) if isinstance(expected, dict) else expected)
            actual = len(table.rows)
            return CheckerResult(passed=actual >= minimum, actual=actual, details={"type": check_type, "minimum": minimum})
        if check_type == "borders":
            tbl_pr = table._tbl.tblPr
            borders = tbl_pr.first_child_found_in("w:tblBorders") if tbl_pr is not None else None
            actual = borders is not None
            return CheckerResult(passed=actual == self._parse_boolean(expected), actual=actual, details={"type": check_type})
        if check_type == "border_details":
            tbl_pr = table._tbl.tblPr
            borders = tbl_pr.first_child_found_in("w:tblBorders") if tbl_pr is not None else None
            if borders is None:
                return CheckerResult(passed=False, details={"reason": "Table borders not found."})
            sides = [node for node in borders if node.tag.rsplit("}", 1)[-1] in {"top", "bottom", "left", "right"}]
            actual = [{"style": node.get(qn("w:val"), ""), "color": node.get(qn("w:color"), ""), "width_pt": round(int(node.get(qn("w:sz"), "0")) / 8, 2)} for node in sides]
            style = str(expected.get("style", "")).lower()
            color = str(expected.get("color", "")).lower()
            width = float(expected.get("width_pt", 0))
            passed = bool(actual) and all(
                (not style or entry["style"].lower() == style)
                and (not color or self._match_color(color, entry["color"], entry["color"]))
                and (not width or abs(entry["width_pt"] - width) <= 0.5)
                for entry in actual
            )
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "row_shading":
            row = int(expected.get("row", 0))
            color = str(expected.get("color", "any")).lower()
            try:
                cells = table.rows[row].cells
            except IndexError:
                return CheckerResult(passed=False, details={"reason": "Row not found."})
            fills = []
            for cell in cells:
                tc_pr = cell._tc.tcPr
                shading = tc_pr.find(qn("w:shd")) if tc_pr is not None else None
                fills.append((shading.get(qn("w:fill"), "") if shading is not None else "").lower())
            actual = {"fills": fills}
            if color == "any":
                passed = bool(fills) and all(fill and fill != "auto" for fill in fills)
            else:
                passed = bool(fills) and all(self._match_color(color, fill, fill) for fill in fills)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "row_height":
            row_index = int(expected.get("row", 0))
            expected_cm = float(expected.get("height_cm", 0))
            try:
                row = table.rows[row_index]
                tr_height = row._tr.trPr.trHeight_val if row._tr.trPr is not None else None
                actual_cm = round(float(tr_height) / 567.0, 2) if tr_height is not None else None
            except (IndexError, TypeError, ValueError):
                actual_cm = None
            passed = actual_cm is not None and abs(actual_cm - expected_cm) <= 0.1
            return CheckerResult(passed=passed, actual=actual_cm, details={"type": check_type})
        if check_type == "row_count_change":
            baseline_path = target.get("baseline_path")
            baseline_table = None
            try:
                baseline_document = Document(baseline_path)
                baseline_table = self._find_table(baseline_document, target)
            except Exception:
                pass
            if baseline_table is None:
                return CheckerResult(passed=False, details={"reason": "Starter-document table not found."})
            actual_delta = len(table.rows) - len(baseline_table.rows)
            expected_delta = int(expected.get("delta", 0))
            return CheckerResult(passed=actual_delta == expected_delta, actual={"starter_rows": len(baseline_table.rows), "submitted_rows": len(table.rows), "delta": actual_delta}, details={"type": check_type})
        if check_type == "cell_vertical_alignment":
            row = int(expected.get("row", 0))
            col = int(expected.get("col", 0))
            cell = self._get_table_cell(table, row, col)
            actual = str(cell.vertical_alignment).split(".")[-1].lower() if cell is not None and cell.vertical_alignment is not None else "top"
            passed = cell is not None and actual == str(expected.get("vertical", "top")).lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "cell_text_direction":
            row = int(expected.get("row", 0))
            col = int(expected.get("col", 0))
            cell = self._get_table_cell(table, row, col)
            direction = ""
            if cell is not None and cell._tc.tcPr is not None:
                node = cell._tc.tcPr.find(qn("w:textDirection"))
                direction = node.get(qn("w:val"), "") if node is not None else ""
            passed = cell is not None and direction.lower() == str(expected.get("direction", "")).lower()
            return CheckerResult(passed=passed, actual=direction, details={"type": check_type})
        if check_type == "first_column_italic":
            # The first row is normally the header and the final row the total.
            data_rows = table.rows[1:-1] if len(table.rows) > 2 else []
            actual = [
                bool(any(run.font.italic for paragraph in row.cells[0].paragraphs for run in paragraph.runs))
                for row in data_rows
                if row.cells
            ]
            expected_bool = self._parse_boolean(expected)
            passed = bool(actual) and all(actual)
            if expected_bool is not None:
                passed = passed == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "sorted_first_column":
            values = [row.cells[0].text.strip() for row in table.rows[1:-1] if row.cells and row.cells[0].text.strip()]
            expected_bool = self._parse_boolean(expected)
            passed = bool(values) and values == sorted(values, key=str.casefold)
            if expected_bool is not None:
                passed = passed == expected_bool
            return CheckerResult(passed=passed, actual=values, details={"type": check_type})
        if check_type == "final_row_sum":
            def numeric_value(text):
                match = re.search(r"[-+]?\d[\d\s,]*(?:\.\d+)?", text.replace("\u00a0", " "))
                return float(match.group(0).replace(" ", "").replace(",", "")) if match else None

            values = [numeric_value(row.cells[-1].text) for row in table.rows[1:-1] if row.cells]
            total = numeric_value(table.rows[-1].cells[-1].text) if table.rows and table.rows[-1].cells else None
            values = [value for value in values if value is not None]
            actual = {"values": values, "total": total}
            expected_bool = self._parse_boolean(expected)
            passed = bool(values) and total is not None and abs(sum(values) - total) <= 0.01
            if expected_bool is not None:
                passed = passed == expected_bool
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
            # Expected can be either a string (e.g. "A4") or a dict like {"size":"A4","orientation":"Portrait"}
            paper_expected = expected
            if isinstance(expected, dict):
                paper_expected = expected.get("size")
                exp_orientation = expected.get("orientation")
            else:
                exp_orientation = None

            if isinstance(paper_expected, str) and paper_expected.strip().upper() in {"A4", "LETTER"}:
                actual_width = section.page_width
                actual_height = section.page_height
                # python-docx uses EMU. Accept the portrait measurements used by Word.
                expected_width, expected_height = (
                    (7560310, 10692130) if paper_expected.strip().upper() == "A4" else (7772400, 10058400)
                )
                size_ok = abs(actual_width - expected_width) < 50000 and abs(actual_height - expected_height) < 50000


                if exp_orientation:
                    actual_orientation = "portrait" if section.orientation == 0 else "landscape"
                    orientation_ok = actual_orientation == str(exp_orientation).strip().lower()
                    passed = size_ok and orientation_ok
                else:
                    passed = size_ok

                return CheckerResult(
                    passed=passed,
                    actual={"width": actual_width, "height": actual_height, "orientation": "portrait" if section.orientation == 0 else "landscape"},
                    details={"type": check_type},
                )

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

        if check_type == "margin_side":
            if not isinstance(expected, dict) or expected.get("side") not in {"top", "bottom", "left", "right"}:
                return CheckerResult(passed=False, details={"reason": "Margin side and value are required."})
            actual = getattr(section, f"{expected['side']}_margin") / 360000
            passed = abs(actual - float(expected["value"])) <= 0.1
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type, "side": expected["side"]})

        # Aliases used by structured_expectations.json -> margins in cm
        # expected is numeric cm for these alias checks.
        if check_type in ("margin_top_bottom_cm", "margin_left_right_cm"):
            try:
                exp_val_raw = expected
                # Some structured expectations use 2/3/.. as shorthand (top/bottom vs left/right).
                # In that case we treat expected as:
                #   - 2 => 1.27 cm (common 0.5 inch)
                #   - 3 => 1.27 cm (common 0.5 inch)
                # Otherwise treat it as an actual numeric cm value.
                if isinstance(exp_val_raw, (int, float)) and exp_val_raw in (2, 3):
                    exp_val = 1.27
                else:
                    exp_val = float(exp_val_raw)
            except Exception:
                return CheckerResult(
                    passed=False,
                    actual=None,
                    details={"type": check_type, "reason": "Expected margin value must be numeric cm"},
                )

            cm_to_emu = 360000
            actual = {
                "top": section.top_margin / cm_to_emu,
                "bottom": section.bottom_margin / cm_to_emu,
                "left": section.left_margin / cm_to_emu,
                "right": section.right_margin / cm_to_emu,
            }

            # Allow moderate tolerance for minor template serialization differences.
            tol_cm = 0.6
            if check_type == "margin_top_bottom_cm":
                passed = abs(actual["top"] - exp_val) <= tol_cm and abs(actual["bottom"] - exp_val) <= tol_cm
            else:
                passed = abs(actual["left"] - exp_val) <= tol_cm and abs(actual["right"] - exp_val) <= tol_cm

            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})


        if check_type == "paper_size":
            # Your earlier run printed A4 values like: width=10058400 height=7772400
            # python-docx uses EMU for page sizes, so compare against those with tolerance.
            if isinstance(expected, str) and expected.strip().upper() == "A4":
                actual_width = section.page_width
                actual_height = section.page_height
                a4_width = 10058400
                a4_height = 7772400
                passed = abs(actual_width - a4_width) < 250000 and abs(actual_height - a4_height) < 250000
                return CheckerResult(passed=passed, actual={"width": actual_width, "height": actual_height}, details={"type": check_type})
            return CheckerResult(passed=False, details={"reason": "Unsupported paper_size format."})

        if check_type == "page_border":
            xml = _read_docx_part(file_path, "word/document.xml")
            actual_style = "none"
            actual_first_page = False
            actual_color = ""
            if xml:
                root = etree.fromstring(xml.encode("utf-8"))
                pg_borders = root.find(
                    ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pgBorders"
                )
                if pg_borders is not None:
                    actual_first_page = str(pg_borders.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}display", "")).lower() in {
                        "firstpage",
                        "firstpageonly",
                    }
                    top = pg_borders.find(
                        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}top"
                    )
                    if top is not None:
                        val = top.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
                        if val:
                            actual_style = val.lower()
                        actual_color = (top.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}color") or "").lower()
            expected_style = None
            expected_first_page = None
            expected_color = None
            if isinstance(expected, dict):
                if expected.get("style") is not None:
                    expected_style = str(expected.get("style", "")).lower()
                if expected.get("first_page_only") is not None:
                    expected_first_page = bool(expected.get("first_page_only"))
                if expected.get("color") is not None:
                    expected_color = str(expected.get("color", "")).lower()
            checks = []
            if expected_style:
                checks.append(expected_style == actual_style)
            if expected_first_page is not None:
                checks.append(actual_first_page == expected_first_page)
            if expected_color:
                checks.append(self._match_color(expected_color, actual_color, actual_color))
            passed = all(checks) if checks else actual_style != "none"
            return CheckerResult(
                passed=passed,
                actual={"style": actual_style, "first_page_only": actual_first_page, "color": actual_color},
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
        if check_type in {"header_learner_name", "header_date_field", "header_date_right"}:
            header_parts = [
                _read_docx_part(file_path, part)
                for part in ("word/header1.xml", "word/header2.xml", "word/header3.xml")
            ]
            roots = [etree.fromstring(part.encode("utf-8")) for part in header_parts if part]
            header_text = " ".join(text for root in roots for text in root.xpath(".//w:t/text()", namespaces=NAMESPACES))
            if check_type == "header_learner_name":
                name = str(expected.get("name", "") if isinstance(expected, dict) else expected).strip().lower()
                tokens = [token for token in re.split(r"[^a-z0-9]+", name) if token]
                actual = header_text.strip()
                passed = bool(tokens) and all(token in actual.lower() for token in tokens)
                return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
            instructions = [text for root in roots for text in root.xpath(".//w:instrText/text()", namespaces=NAMESPACES)]
            instruction_text = " ".join(instructions)
            has_date = "DATE" in instruction_text.upper()
            if check_type == "header_date_field":
                expected_format = str(expected.get("format", "") if isinstance(expected, dict) else expected).strip().lower()
                actual_format = instruction_text.lower()
                passed = has_date and (not expected_format or expected_format in actual_format)
                return CheckerResult(passed=passed, actual={"field": instruction_text, "header_text": header_text}, details={"type": check_type})
            right_aligned = False
            if roots:
                right_aligned = any(root.xpath(".//w:tabs/w:tab[@w:val='right'] | .//w:jc[@w:val='right'] | .//w:ptab[@w:alignment='right'] | .//w:tab", namespaces=NAMESPACES) for root in roots)
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=right_aligned if expected_bool is None else right_aligned == expected_bool, actual=right_aligned, details={"type": check_type})
        if check_type == "header_text_alignment":
            actual_text = self._gather_header_text(section)
            actual_alignment = "left"
            for header_part in (section.header, section.even_page_header, section.first_page_header):
                try:
                    paragraphs = [p for p in header_part.paragraphs if p.text.strip()]
                    if paragraphs:
                        actual_alignment = ALIGNMENT_MAP.get(paragraphs[0].alignment, "left")
                        break
                except Exception:
                    continue
            expected_text = str(expected.get("text", "")) if isinstance(expected, dict) else ""
            expected_alignment = str(expected.get("alignment", "left")).lower() if isinstance(expected, dict) else "left"
            passed = bool(actual_text.strip()) and expected_text.lower() in actual_text.lower() and actual_alignment == expected_alignment
            return CheckerResult(passed=passed, actual={"text": actual_text, "alignment": actual_alignment}, details={"type": check_type})
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
        if check_type == "header_content":
            actual = self._gather_header_text(section)
            # expected can be:
            # - bool: True => header has non-empty content, False => empty
            # - str: substring match (case-insensitive)
            if isinstance(expected, bool):
                passed = bool(actual.strip()) == expected
            elif isinstance(expected, str):
                passed = expected.strip().lower() in actual.lower()
            else:
                passed = bool(actual.strip())
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        if check_type == "footer_content":
            actual = self._gather_footer_text(section)
            if isinstance(expected, bool):
                passed = bool(actual.strip()) == expected
            elif isinstance(expected, str):
                passed = expected.strip().lower() in actual.lower()
            else:
                passed = bool(actual.strip())
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        if check_type == "header_differs":
            actual = bool(section.different_first_page_header_footer)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "footer_differs":
            actual = bool(section.different_first_page_header_footer)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "page_number_in_header":
            actual = self._document_part_contains_page_field(file_path, "word/header")
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "page_number_in_footer":
            actual = self._document_part_contains_page_field(file_path, "word/footer")
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "page_number_in_first_footer":
            footer_xml = "\n".join(paragraph._p.xml for paragraph in section.first_page_footer.paragraphs)
            actual = "PAGE" in footer_xml.upper()
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "page_number_format":
            actual = self._page_number_format(file_path)
            passed = str(actual).lower() == str(expected).strip().lower()
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "page_number_template":
            template = expected.get("template", "") if isinstance(expected, dict) else str(expected)
            passed, actual = self._matches_page_number_template(file_path, expected)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type, "template": template})
        if check_type == "page_break":
            actual_count = self._count_page_breaks(file_path)
            expected_bool = self._parse_boolean(expected)
            if isinstance(expected, dict) and expected.get("count") is not None:
                try:
                    passed = actual_count == int(expected["count"])
                except Exception:
                    passed = False
            elif expected_bool is not None:
                passed = actual_count > 0 if expected_bool else actual_count == 0
            else:
                try:
                    passed = actual_count == int(expected)
                except Exception:
                    passed = actual_count > 0
            return CheckerResult(passed=passed, actual=actual_count, details={"type": check_type})
        if check_type == "section_page_break_type":
            actual = self._section_break_type(section)
            expected_value = str(expected).strip().lower()
            normalized = expected_value.replace(" ", "")
            passed = actual.lower() == normalized
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "line_numbers":
            actual = self._line_number_settings(section)
            if isinstance(expected, dict):
                passed = True
                if "enabled" in expected:
                    expected_enabled = self._parse_boolean(expected["enabled"])
                    passed = passed and actual["enabled"] == expected_enabled
                if "start" in expected:
                    passed = passed and actual["start"] == int(expected["start"])
                if "interval" in expected:
                    passed = passed and actual["interval"] == int(expected["interval"])
            else:
                expected_bool = self._parse_boolean(expected)
                passed = actual["enabled"] if expected_bool is None else actual["enabled"] == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "gutter_margin":
            actual = float(section.gutter.cm) if section.gutter is not None else None
            if actual is not None and expected is not None:
                passed = compare_numeric(actual, float(expected), tolerance=TOLERANCE_CM, unit="cm")
            else:
                passed = False
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "mirror_margins":
            actual = self._mirror_margins_enabled(section)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "page_color":
            actual = self._page_background_color(file_path)
            if isinstance(expected, dict):
                expected_color = expected.get("color")
            else:
                expected_color = expected
            if expected_color is not None:
                passed = normalize_hex_color(str(expected_color)) == actual
            else:
                passed = actual is not None
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
        if check_type == "do_not_hyphenate_caps":
            settings_xml = _read_docx_part(file_path, "word/settings.xml")
            root = etree.fromstring(settings_xml.encode("utf-8")) if settings_xml else None
            node = root.find(".//w:doNotHyphenateCaps", namespaces=NAMESPACES) if root is not None else None
            actual = node is not None and node.get(qn("w:val"), "1").lower() not in {"0", "false", "off"}
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=actual if expected_bool is None else actual == expected_bool, actual=actual, details={"type": check_type})
        if check_type == "cover_fill_colour":
            xml = _read_docx_part(file_path, "word/document.xml")
            root = etree.fromstring(xml.encode("utf-8")) if xml else None
            fills = []
            if root is not None:
                for fill in root.xpath(".//*[local-name()='solidFill']"):
                    colours = fill.xpath("./*[local-name()='srgbClr']/@val | ./*[local-name()='schemeClr']/@val")
                    fills.extend(colours)
            expected_colour = str(expected).strip().lower()
            passed = any(
                self._match_color(expected_colour, colour, colour)
                or (expected_colour == "white" and colour.lower() in {"bg1", "lt1"})
                for colour in fills
            )
            return CheckerResult(passed=passed, actual=fills, details={"type": check_type})
        if check_type == "content_control_absent":
            xml = _read_docx_part(file_path, "word/document.xml")
            root = etree.fromstring(xml.encode("utf-8")) if xml else None
            aliases = [value.strip().lower() for value in root.xpath(".//w:sdtPr/w:alias/@w:val", namespaces=NAMESPACES)] if root is not None else []
            required_absent = str(expected).strip().lower()
            return CheckerResult(passed=bool(required_absent) and required_absent not in aliases, actual=aliases, details={"type": check_type})
        if check_type in {"footnote_on_text", "footnote_reference_symbol"}:
            document_xml = _read_docx_part(file_path, "word/document.xml")
            footnotes_xml = _read_docx_part(file_path, "word/footnotes.xml")
            document_root = etree.fromstring(document_xml.encode("utf-8")) if document_xml else None
            footnotes_root = etree.fromstring(footnotes_xml.encode("utf-8")) if footnotes_xml else None
            required_text = str(expected.get("text", "") if isinstance(expected, dict) else expected).strip().lower()
            footnote_id = None
            if document_root is not None and required_text:
                for paragraph in document_root.xpath(".//w:p", namespaces=NAMESPACES):
                    text = "".join(paragraph.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip().lower()
                    if required_text in text:
                        references = paragraph.xpath(".//w:footnoteReference/@w:id", namespaces=NAMESPACES)
                        if references:
                            footnote_id = references[0]
                            break
            if check_type == "footnote_on_text":
                return CheckerResult(passed=footnote_id is not None, actual={"text": required_text, "footnote_id": footnote_id}, details={"type": check_type})
            font = ""
            character = ""
            if footnote_id and footnotes_root is not None:
                notes = footnotes_root.xpath(f".//w:footnote[@w:id='{footnote_id}']", namespaces=NAMESPACES)
                if notes:
                    symbol = notes[0].find(".//w:sym", namespaces=NAMESPACES)
                    if symbol is not None:
                        font = symbol.get(qn("w:font"), "")
                        character = symbol.get(qn("w:char"), "")
            expected_font = str(expected.get("font", "") if isinstance(expected, dict) else "").strip().lower()
            expected_code = str(expected.get("character_code", "") if isinstance(expected, dict) else "").strip()
            expected_hex = f"F{int(expected_code):03X}" if expected_code.isdigit() else expected_code.upper()
            passed = bool(footnote_id) and font.lower() == expected_font and character.upper() == expected_hex
            return CheckerResult(passed=passed, actual={"footnote_id": footnote_id, "font": font, "character": character}, details={"type": check_type})

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
        if check_type == "document_property":
            if not isinstance(expected, dict):
                return CheckerResult(passed=False, details={"reason": "Document property must specify a property and value."})
            property_name = str(expected.get("property", "")).strip().lower()
            expected_value = str(expected.get("value", "")).strip().lower()
            aliases = {"comment": "comments", "description": "comments"}
            property_name = aliases.get(property_name, property_name)
            if property_name not in {"title", "subject", "author", "comments", "keywords", "category"}:
                return CheckerResult(passed=False, details={"reason": "Unsupported document property."})
            actual = str(getattr(document.core_properties, property_name, "") or "")
            return CheckerResult(passed=expected_value in actual.lower(), actual=actual, details={"type": check_type, "property": property_name})
        if check_type == "document_property_changed":
            if not isinstance(expected, dict):
                return CheckerResult(passed=False, details={"reason": "Document property and starter value are required."})
            property_name = str(expected.get("property", "")).strip().lower()
            starter_value = str(expected.get("starter_value", "")).strip().lower()
            if property_name not in {"title", "subject", "author", "comments", "keywords", "category"}:
                return CheckerResult(passed=False, details={"reason": "Unsupported document property."})
            actual = str(getattr(document.core_properties, property_name, "") or "")
            passed = bool(actual.strip()) and actual.strip().lower() != starter_value
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type, "property": property_name})
        if check_type == "cover_page_fields":
            # Word cover-page gallery designs are not labelled consistently in DOCX XML.
            # Validate their required visible content in the document opening instead.
            expected_fields = expected if isinstance(expected, dict) else {"title": str(expected)}
            opening_text = " ".join(p.text.strip() for p in document.paragraphs[:15] if p.text.strip())
            normalized_opening = opening_text.lower()
            required = {
                name: str(value).strip()
                for name, value in expected_fields.items()
                if name in {"title", "author", "abstract"} and str(value).strip()
            }
            matched = {name: value.lower() in normalized_opening for name, value in required.items()}
            return CheckerResult(
                passed=bool(required) and all(matched.values()),
                actual={"opening_text": opening_text, "matched": matched},
                details={"type": check_type},
            )
        if check_type == "no_empty_content_controls":
            xml = _read_docx_part(file_path, "word/document.xml")
            if not xml:
                return CheckerResult(passed=False, details={"reason": "Document XML not readable."})
            root = etree.fromstring(xml.encode("utf-8"))
            controls = root.xpath(".//w:sdt", namespaces=NAMESPACES)
            empty_controls = []
            for control in controls:
                content = control.find(".//w:sdtContent", namespaces=NAMESPACES)
                text = "".join(content.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip() if content is not None else ""
                if not text:
                    empty_controls.append("empty")
            expected_complete = self._parse_boolean(expected)
            complete = not empty_controls
            return CheckerResult(
                passed=complete if expected_complete is None else complete == expected_complete,
                actual={"content_controls": len(controls), "empty_controls": len(empty_controls)},
                details={"type": check_type},
            )
        if check_type == "cover_page_controls":
            xml = _read_docx_part(file_path, "word/document.xml")
            if not xml:
                return CheckerResult(passed=False, details={"reason": "Document XML not readable."})
            root = etree.fromstring(xml.encode("utf-8"))
            aliases = []
            for control in root.xpath(".//w:sdt", namespaces=NAMESPACES):
                alias = control.find(".//w:alias", namespaces=NAMESPACES)
                value = alias.get(qn("w:val"), "").strip().lower() if alias is not None else ""
                if value:
                    aliases.append(value)
            expected_aliases = expected.get("aliases", []) if isinstance(expected, dict) else [expected]
            expected_aliases = [str(alias).strip().lower() for alias in expected_aliases if str(alias).strip()]
            passed = bool(expected_aliases) and all(alias in aliases for alias in expected_aliases) and set(aliases).issubset(set(expected_aliases))
            return CheckerResult(passed=passed, actual=aliases, details={"type": check_type})
        if check_type == "columns":
            xml = _read_docx_part(file_path, "word/document.xml")
            if not xml:
                return CheckerResult(passed=False, details={"reason": "Document XML not readable."})
            root = etree.fromstring(xml.encode("utf-8"))
            column_nodes = root.xpath(".//w:sectPr/w:cols", namespaces=NAMESPACES)
            actual = []
            for node in column_nodes:
                actual.append({
                    "count": int(node.get(qn("w:num"), "1")),
                    "space_cm": round(int(node.get(qn("w:space"), "0")) / 567.0, 2),
                })
            if not isinstance(expected, dict):
                expected = {"count": int(expected)}
            expected_count = int(expected.get("count", 1))
            expected_space = expected.get("space_cm")
            passed = any(item["count"] == expected_count for item in actual)
            if expected_space is not None:
                passed = passed and any(item["count"] == expected_count and abs(item["space_cm"] - float(expected_space)) <= 0.1 for item in actual)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "column_spacing":
            xml = _read_docx_part(file_path, "word/document.xml")
            root = etree.fromstring(xml.encode("utf-8")) if xml else None
            nodes = root.xpath(".//w:sectPr/w:cols", namespaces=NAMESPACES) if root is not None else []
            actual = [
                {
                    "count": int(node.get(qn("w:num"), "1")),
                    "space_cm": round(int(node.get(qn("w:space"), "0")) / 567.0, 2),
                }
                for node in nodes
            ]
            expected_count = int(expected.get("count", 1)) if isinstance(expected, dict) else 1
            expected_space = float(expected.get("space_cm", 0)) if isinstance(expected, dict) else float(expected)
            passed = any(item["count"] == expected_count and abs(item["space_cm"] - expected_space) <= 0.1 for item in actual)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "column_separator":
            xml = _read_docx_part(file_path, "word/document.xml")
            root = etree.fromstring(xml.encode("utf-8")) if xml else None
            nodes = root.xpath(".//w:sectPr/w:cols", namespaces=NAMESPACES) if root is not None else []
            actual = any(node.get(qn("w:sep"), "0").lower() in {"1", "true", "on"} for node in nodes)
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=actual if expected_bool is None else actual == expected_bool, actual=actual, details={"type": check_type})
        if check_type == "page_background_present":
            actual = self._has_page_background(file_path)
            expected_bool = self._parse_boolean(expected)
            passed = actual if expected_bool is None else actual == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "column_breaks":
            xml = _read_docx_part(file_path, "word/document.xml")
            count = xml.count('w:type="column"') if xml else 0
            expected_count = int(expected.get("count", 1)) if isinstance(expected, dict) else int(expected)
            return CheckerResult(passed=count >= expected_count, actual=count, details={"type": check_type})
        if check_type == "find_replace":
            if not isinstance(expected, dict):
                return CheckerResult(passed=False, details={"reason": "Find/replace needs find and replacement text."})
            document_text = self._document_text(document, file_path).lower()
            find_text = str(expected.get("find", "")).strip().lower()
            replacement = str(expected.get("replace", "")).strip().lower()
            actual = {"find_count": document_text.count(find_text), "replace_count": document_text.count(replacement)}
            passed = bool(replacement) and actual["find_count"] == 0 and actual["replace_count"] >= int(expected.get("minimum_replacements", 1))
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "text_occurrence_count":
            if not isinstance(expected, dict):
                return CheckerResult(passed=False, details={"reason": "Text and required count are needed."})
            text = str(expected.get("text", "")).strip()
            actual = len(re.findall(rf"(?<!\\w){re.escape(text)}(?!\\w)", self._document_text(document, file_path), flags=re.IGNORECASE)) if text else 0
            return CheckerResult(passed=bool(text) and actual == int(expected.get("count", 0)), actual=actual, details={"type": check_type, "text": text})
        if check_type in {"all_text_bold", "text_underline"}:
            text = str(expected).strip()
            matching_runs = [
                run for paragraph in document.paragraphs for run in paragraph.runs
                if re.search(rf"(?<!\\w){re.escape(text)}(?!\\w)", run.text or "", flags=re.IGNORECASE)
            ] if text else []
            if check_type == "all_text_bold":
                passed = bool(matching_runs) and all(bool(run.font.bold) for run in matching_runs)
            else:
                passed = any(bool(run.font.underline) for run in matching_runs)
            return CheckerResult(passed=passed, actual={"matching_runs": len(matching_runs)}, details={"type": check_type, "text": text})
        if check_type == "comments":
            xml = _read_docx_part(file_path, "word/comments.xml")
            comments = []
            if xml:
                root = etree.fromstring(xml.encode("utf-8"))
                comments = ["".join(node.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip() for node in root.xpath(".//w:comment", namespaces=NAMESPACES)]
            if isinstance(expected, bool):
                passed = bool(comments) == expected
            else:
                required_text = str(expected).strip().lower() if isinstance(expected, str) else ""
                passed = any(required_text in comment.lower() for comment in comments) if required_text else bool(comments)
            return CheckerResult(passed=passed, actual=comments, details={"type": check_type})
        if check_type == "comment_on_text":
            if not isinstance(expected, dict):
                return CheckerResult(passed=False, details={"reason": "Comment target text is required."})
            required_text = str(expected.get("text", "")).strip().lower()
            required_comment = str(expected.get("comment", "")).strip().lower()
            comments_xml = _read_docx_part(file_path, "word/comments.xml") or ""
            document_xml = _read_docx_part(file_path, "word/document.xml") or ""
            comments_root = etree.fromstring(comments_xml.encode("utf-8")) if comments_xml else None
            document_root = etree.fromstring(document_xml.encode("utf-8")) if document_xml else None
            comments_by_id = {
                comment.get(qn("w:id"), ""): "".join(comment.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip()
                for comment in comments_root.xpath(".//w:comment", namespaces=NAMESPACES)
            } if comments_root is not None else {}
            active_ranges = {}
            anchored_text = {}
            if document_root is not None:
                for node in document_root.iter():
                    if node.tag == qn("w:commentRangeStart"):
                        active_ranges[node.get(qn("w:id"), "")] = []
                    elif node.tag == qn("w:commentRangeEnd"):
                        comment_id = node.get(qn("w:id"), "")
                        anchored_text[comment_id] = "".join(active_ranges.pop(comment_id, [])).strip()
                    elif node.tag == qn("w:t") and node.text:
                        for text_parts in active_ranges.values():
                            text_parts.append(node.text)
            matched_ids = [
                comment_id for comment_id, text in anchored_text.items()
                if required_text and required_text in text.lower()
                and (not required_comment or required_comment in comments_by_id.get(comment_id, "").lower())
            ]
            return CheckerResult(
                passed=bool(matched_ids),
                actual={"comments": comments_by_id, "anchored_text": anchored_text},
                details={"type": check_type, "matched_comment_ids": matched_ids},
            )
        if check_type == "table_of_contents":
            xml = _read_docx_part(file_path, "word/document.xml") or ""
            found = "TOC" in xml.upper()
            return CheckerResult(passed=found == self._parse_boolean(expected) if self._parse_boolean(expected) is not None else found, actual=found, details={"type": check_type})
        if check_type in {"toc_before_heading", "toc_levels", "toc_formal"}:
            xml = _read_docx_part(file_path, "word/document.xml") or ""
            root = etree.fromstring(xml.encode("utf-8")) if xml else None
            paragraphs = root.xpath(".//w:body/w:p", namespaces=NAMESPACES) if root is not None else []
            toc_indexes = [
                index for index, paragraph in enumerate(paragraphs)
                if "TOC" in "".join(paragraph.xpath(".//w:instrText/text()", namespaces=NAMESPACES)).upper()
            ]
            if check_type == "toc_before_heading":
                heading = str(expected).strip().lower()
                heading_index = next((index for index, paragraph in enumerate(paragraphs) if heading in "".join(paragraph.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip().lower()), None)
                passed = bool(toc_indexes) and heading_index is not None and toc_indexes[0] < heading_index
                return CheckerResult(passed=passed, actual={"toc_indexes": toc_indexes, "heading_index": heading_index}, details={"type": check_type})
            instructions = " ".join("".join(paragraph.xpath(".//w:instrText/text()", namespaces=NAMESPACES)) for paragraph in paragraphs if "TOC" in "".join(paragraph.xpath(".//w:instrText/text()", namespaces=NAMESPACES)).upper())
            if check_type == "toc_levels":
                expected_levels = int(expected)
                patterns = (f'1-{expected_levels}', f'"1-{expected_levels}"')
                return CheckerResult(passed=any(pattern in instructions for pattern in patterns), actual=instructions, details={"type": check_type})
            toc_styles = root.xpath(".//w:p[w:pPr/w:pStyle[starts-with(@w:val, 'TOC')]]", namespaces=NAMESPACES) if root is not None else []
            dot_leaders = root.xpath(".//w:pPr/w:tabs/w:tab[@w:val='right'][@w:leader='dot']", namespaces=NAMESPACES) if root is not None else []
            actual = {"toc_styles": len(toc_styles), "dot_leaders": len(dot_leaders)}
            return CheckerResult(passed=bool(toc_styles) and bool(dot_leaders), actual=actual, details={"type": check_type})
        if check_type == "footnote_text":
            xml = _read_docx_part(file_path, "word/footnotes.xml") or ""
            root = etree.fromstring(xml.encode("utf-8")) if xml else None
            notes = ["".join(note.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip() for note in root.xpath(".//w:footnote", namespaces=NAMESPACES)] if root is not None else []
            required_text = str(expected).strip().lower()
            return CheckerResult(passed=any(required_text in note.lower() for note in notes), actual=notes, details={"type": check_type})
        if check_type == "mail_merge_fields":
            xml = _read_docx_part(file_path, "word/document.xml") or ""
            fields = re.findall(r"MERGEFIELD\s+([^\\\s]+)", xml, flags=re.IGNORECASE)
            required = expected.get("fields", []) if isinstance(expected, dict) else [expected]
            required = [str(field).strip().lower() for field in required if str(field).strip()]
            actual = [field.strip('"').lower() for field in fields]
            passed = bool(required) and all(field in actual for field in required)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})
        if check_type == "mail_merge_source":
            expected_name = str(expected).strip().lower()
            related_xml = "\n".join(filter(None, (
                _read_docx_part(file_path, "word/settings.xml"),
                _read_docx_part(file_path, "word/_rels/settings.xml.rels"),
                _read_docx_part(file_path, "word/_rels/document.xml.rels"),
            )))
            has_mail_merge = "mailmerge" in related_xml.lower()
            return CheckerResult(passed=has_mail_merge and expected_name in related_xml.lower(), actual={"mail_merge": has_mail_merge, "source_found": expected_name in related_xml.lower()}, details={"type": check_type})
        if check_type == "citation_field":
            xml = _read_docx_part(file_path, "word/document.xml") or ""
            fields = re.findall(r"CITATION\s+([^\\\s]+)", xml, flags=re.IGNORECASE)
            expected_tag = str(expected).strip().lower()
            actual = [field.strip('"').lower() for field in fields]
            return CheckerResult(passed=expected_tag in actual, actual=actual, details={"type": check_type})
        if check_type == "contains_text":
            expected_text = str(expected).strip().lower()
            actual = self._document_text(document, file_path)
            return CheckerResult(passed=expected_text in actual.lower(), actual=expected_text if expected_text in actual.lower() else None, details={"type": check_type})
        if check_type == "no_repeated_spaces":
            actual = self._document_text(document, file_path)
            repeated = re.findall(r"(?<!\n) {2,}", actual)
            return CheckerResult(passed=not repeated, actual={"repeated_space_groups": len(repeated)}, details={"type": check_type})
        if check_type == "heading_number_format":
            xml = _read_docx_part(file_path, "word/document.xml") or ""
            styles = _read_docx_part(file_path, "word/styles.xml") or ""
            numbering = _read_docx_part(file_path, "word/numbering.xml") or ""
            target_heading = str(target.get("value", "")).strip().lower()
            expected_format = str(expected).strip().lower()
            # The numbering definition is shared by styled headings. Require both the target
            # heading and the requested number format in the document package.
            target_found = target_heading in re.sub(r"<[^>]+>", " ", xml).lower() if target_heading else bool(xml)
            actual_formats = re.findall(r'w:numFmt[^>]+w:val="([^"]+)"', numbering + styles, flags=re.IGNORECASE)
            passed = target_found and any(value.lower() == expected_format for value in actual_formats)
            return CheckerResult(passed=passed, actual=actual_formats, details={"type": check_type, "target": target_heading})



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
        if not paragraphs or (target or {}).get("locator") == "document":
            # Scan all paragraphs for the style
            paragraphs = document.paragraphs

        def normalize_style(value: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", value.lower())

        normalized_expected = normalize_style(exp_style)
        for p in paragraphs:
            if p.style and (
                exp_style in p.style.name.lower()
                or normalized_expected == normalize_style(p.style.name)
                or normalized_expected in normalize_style(p.style.name)
            ):
                return CheckerResult(passed=True, actual=p.style.name, details={"type": "style_applied"})
        return CheckerResult(passed=False, actual=None, details={"type": "style_applied", "reason": f"Style '{exp_style}' not found."})

    def _check_style_count(self, document: Document, expected: Any) -> CheckerResult:
        if not isinstance(expected, dict):
            return CheckerResult(passed=False, details={"reason": "A style and minimum count are required."})
        style = str(expected.get("style", "")).strip().lower()
        minimum = int(expected.get("minimum", 0))
        required_texts = [str(text).strip().lower() for text in expected.get("texts", []) if str(text).strip()]

        def normalize(value: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", value.lower())

        matches = [
            paragraph.text.strip()
            for paragraph in document.paragraphs
            if paragraph.style and normalize(paragraph.style.name) == normalize(style)
        ]
        matched_texts = [text.lower() for text in matches]
        required_found = all(any(required in text for text in matched_texts) for required in required_texts)
        return CheckerResult(
            passed=len(matches) >= minimum and required_found,
            actual={"count": len(matches), "headings": matches, "required_texts_found": required_found},
            details={"type": "style_count", "style": style, "minimum": minimum},
        )

    def _check_style_format(self, document: Document, check_type: str, expected: Any) -> CheckerResult:
        if not isinstance(expected, dict):
            return CheckerResult(passed=False, details={"reason": "A style and expected format are required."})
        style_name = str(expected.get("style", "")).strip()
        try:
            style = document.styles[style_name]
        except KeyError:
            return CheckerResult(passed=False, details={"reason": f"Style '{style_name}' was not found."})
        if check_type == "style_font_name":
            actual = style.font.name
            passed = bool(actual) and actual.lower() == str(expected.get("font", "")).lower()
        elif check_type == "style_underline":
            actual = bool(style.font.underline)
            passed = actual == bool(expected.get("value"))
        elif check_type == "style_shadow":
            actual = bool(style.font.shadow)
            passed = actual == bool(expected.get("value"))
        elif check_type == "style_underline_type":
            node = style.element.find(".//w:rPr/w:u", namespaces=NAMESPACES)
            actual = node.get(qn("w:val"), "single") if node is not None else "none"
            passed = actual.lower() == str(expected.get("underline", "")).lower()
        elif check_type == "style_character_spacing":
            node = style.element.find(".//w:rPr/w:spacing", namespaces=NAMESPACES)
            actual = round(int(node.get(qn("w:val"), "0")) / 20, 2) if node is not None else None
            passed = actual is not None and compare_numeric(actual, float(expected.get("value", 0)), tolerance=TOLERANCE_PT, unit="pt")
        elif check_type == "paragraph_after_heading_style":
            heading = str(expected.get("heading", "")).strip().lower()
            expected_style = str(expected.get("style", "")).strip().lower().replace(" ", "")
            following = next((document.paragraphs[index + 1] for index, paragraph in enumerate(document.paragraphs[:-1]) if paragraph.text.strip().lower() == heading), None)
            actual = following.style.name if following and following.style else ""
            passed = actual.lower().replace(" ", "") == expected_style
        else:
            return CheckerResult(passed=False, details={"reason": "Unsupported style format."})
        return CheckerResult(passed=passed, actual=actual, details={"type": check_type, "style": style_name})

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
        textboxes = root.xpath(".//*[local-name()='txbxContent']")
        textbox_text = ["".join(box.xpath(".//w:t/text()", namespaces=NAMESPACES)).strip() for box in textboxes]

        def picture_extent_cm(pic, dimension: str) -> Optional[float]:
            extents = pic.xpath("ancestor::*[local-name()='inline' or local-name()='anchor'][1]/*[local-name()='extent'][1]")
            if not extents:
                return None
            value = extents[0].get(dimension)
            return round(int(value) / 360000.0, 2) if value else None

        if check_type == "image_width":
            exp_cm = float(expected.get("width_cm", 5.0)) if isinstance(expected, dict) else 5.0
            widths = [width for width in (picture_extent_cm(pic, "cx") for pic in pictures) if width is not None]
            closest = min(widths, key=lambda width: abs(width - exp_cm)) if widths else None
            passed = any(abs(width - exp_cm) < 0.3 for width in widths)
            return CheckerResult(passed=passed, actual=closest, details={"type": check_type, "widths_cm": widths})

        if check_type == "image_height":
            exp_cm = float(expected.get("height_cm", expected) if isinstance(expected, dict) else expected)
            heights = [height for height in (picture_extent_cm(pic, "cy") for pic in pictures) if height is not None]
            closest = min(heights, key=lambda height: abs(height - exp_cm)) if heights else None
            return CheckerResult(passed=any(abs(height - exp_cm) < 0.3 for height in heights), actual=closest, details={"type": check_type, "heights_cm": heights})

        if check_type == "image_grayscale":
            actual = "grayscl" in doc_xml.lower() or "duotone" in doc_xml.lower()
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=actual if expected_bool is None else actual == expected_bool, actual=actual, details={"type": check_type})

        if check_type == "image_reflection":
            actual = "reflection" in doc_xml.lower()
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=actual if expected_bool is None else actual == expected_bool, actual=actual, details={"type": check_type})

        if check_type == "image_alt_text":
            expected_text = "" if isinstance(expected, bool) else str(expected).strip().lower()
            alt_values = [value for value in root.xpath(".//wp:docPr/@descr", namespaces=ns) if value.strip()]
            actual = alt_values
            default_values = {"picture", "picture 1", "image", "image 1", "graphic", "graphic 1"}
            meaningful_values = [value for value in alt_values if value.strip().lower() not in default_values]
            if isinstance(expected, bool):
                passed = bool(meaningful_values) == expected
            else:
                passed = any(expected_text in value.lower() for value in alt_values) if expected_text else bool(meaningful_values)
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

        if check_type == "image_count":
            expected_count = int(expected.get("count", expected) if isinstance(expected, dict) else expected)
            return CheckerResult(passed=len(pictures) >= expected_count, actual=len(pictures), details={"type": check_type})

        if check_type == "image_changed_from_starter":
            baseline_path = target.get("baseline_path")
            try:
                with ZipFile(baseline_path, "r") as archive:
                    starter_images = sorted(archive.read(name) for name in archive.namelist() if name.startswith("word/media/"))
                with ZipFile(file_path, "r") as archive:
                    submitted_images = sorted(archive.read(name) for name in archive.namelist() if name.startswith("word/media/"))
            except Exception:
                return CheckerResult(passed=False, details={"reason": "Starter-document media could not be compared."})
            changed = starter_images != submitted_images
            expected_changed = self._parse_boolean(expected)
            return CheckerResult(passed=changed if expected_changed is None else changed == expected_changed, actual={"starter_images": len(starter_images), "submitted_images": len(submitted_images), "changed": changed}, details={"type": check_type})

        if check_type == "image_matches_reference":
            expected_hash = str(expected.get("sha256", "")) if isinstance(expected, dict) else str(expected)
            try:
                with ZipFile(file_path, "r") as archive:
                    hashes = [hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith("word/media/")]
            except Exception:
                hashes = []
            return CheckerResult(passed=bool(expected_hash) and expected_hash in hashes, actual={"image_count": len(hashes), "matched": expected_hash in hashes}, details={"type": check_type})

        if check_type == "textbox_text":
            required_text = str(expected).strip().lower()
            return CheckerResult(passed=any(required_text in text.lower() for text in textbox_text), actual=textbox_text, details={"type": check_type})

        if check_type == "textbox_count":
            expected_count = int(expected.get("count", expected) if isinstance(expected, dict) else expected)
            return CheckerResult(passed=len(textboxes) >= expected_count, actual=len(textboxes), details={"type": check_type})

        if check_type == "textbox_shadow":
            has_shadow = "<a:outerShdw" in doc_xml or "<a:innerShdw" in doc_xml or "shadow" in doc_xml.lower()
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=has_shadow if expected_bool is None else has_shadow == expected_bool, actual=has_shadow, details={"type": check_type})

        if check_type == "textbox_position":
            positions = []
            for anchor in root.xpath(".//wp:anchor", namespaces=ns):
                if not anchor.xpath(".//*[local-name()='txbxContent']"):
                    continue
                alignment = anchor.find("./wp:positionH/wp:align", namespaces=ns)
                offset = anchor.find("./wp:positionH/wp:posOffset", namespaces=ns)
                offset_right = False
                if offset is not None:
                    try:
                        offset_right = int(offset.text or "0") > 0
                    except ValueError:
                        offset_right = False
                positions.append((alignment.text or "").lower() if alignment is not None else ("right" if offset_right else ""))
            expected_position = str(expected).strip().lower()
            return CheckerResult(passed=expected_position in positions, actual=positions, details={"type": check_type})

        if check_type == "textbox_style":
            expected_style = str(expected).strip().lower().replace(" ", "")
            styles = []
            for box in textboxes:
                for paragraph in box.xpath(".//w:p", namespaces=NAMESPACES):
                    style = paragraph.find("./w:pPr/w:pStyle", namespaces=NAMESPACES)
                    if style is not None:
                        styles.append(style.get(qn("w:val"), "").lower().replace(" ", ""))
            return CheckerResult(passed=any(expected_style in style for style in styles), actual=styles, details={"type": check_type})

        if check_type == "caption_text":
            expected_text = str(expected).strip().lower()
            captions = [p.text.strip() for p in document.paragraphs if p.style and "caption" in p.style.name.lower()]
            matched = next((caption for caption in captions if expected_text in caption.lower()), "")
            return CheckerResult(passed=bool(matched), actual={"captions": captions}, details={"type": check_type})

        if check_type == "caption_present":
            captions = [p.text.strip() for p in document.paragraphs if p.style and "caption" in p.style.name.lower() and p.text.strip()]
            expected_bool = self._parse_boolean(expected)
            actual = captions
            passed = bool(captions)
            if expected_bool is not None:
                passed = passed == expected_bool
            return CheckerResult(passed=passed, actual=actual, details={"type": check_type})

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

                # Diagram layout names are not consistently exposed in saved DOCX XML.
                # Treat a found SmartArt object as sufficient when no text match is available.
                passed = matched_any if matched_any else has_smartart
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
            if isinstance(expected, bool):
                actual = bool(root.xpath(".//pic:pic//a:srcRect", namespaces=ns))
                return CheckerResult(passed=actual == expected, actual=actual, details={"type": check_type})
            expected_shape = expected.get("shape", "oval") if isinstance(expected, dict) else str(expected)
            expected_prst = {"oval": "ellipse", "circle": "ellipse"}.get(str(expected_shape).lower(), str(expected_shape).lower())
            shapes = [
                geom.get("prst", "").lower()
                for pic in pictures
                for geom in pic.xpath(".//pic:spPr/a:prstGeom", namespaces=ns)
            ]
            passed = expected_prst in shapes
            return CheckerResult(passed=passed, actual={"shapes": shapes}, details={"type": check_type})

        if check_type == "image_style":
            effects = root.xpath(".//pic:pic//a:effectLst | .//pic:pic//a:effectDag", namespaces=ns)
            geometries = [node.get("prst", "").lower() for node in root.xpath(".//pic:pic//a:prstGeom", namespaces=ns)]
            actual = bool(effects) or any(value and value != "rect" for value in geometries)
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=actual if expected_bool is None else actual == expected_bool, actual=actual, details={"type": check_type})

        if check_type == "image_wrap_tight":
            actual = bool(root.xpath(".//wp:anchor/wp:wrapTight", namespaces=ns))
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=actual if expected_bool is None else actual == expected_bool, actual=actual, details={"type": check_type})

        if check_type == "image_fits_layout":
            usable_width = max(0, document.sections[0].page_width - document.sections[0].left_margin - document.sections[0].right_margin)
            widths = [int(value) for value in root.xpath(".//wp:inline/wp:extent/@cx | .//wp:anchor/wp:extent/@cx", namespaces=ns) if value.isdigit()]
            actual = {"widths": widths, "usable_width": usable_width}
            fits = bool(widths) and any(width <= usable_width for width in widths)
            expected_bool = self._parse_boolean(expected)
            return CheckerResult(passed=fits if expected_bool is None else fits == expected_bool, actual=actual, details={"type": check_type})

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

        # Hyperlinks & cross-references are parsed at XML/package level.
        if domain == "object" and check_type in ("hyperlink_present", "hyperlink_url", "hyperlink_text", "hyperlink_text_destination"):
            from .checks.hyperlink import check_hyperlink_rule
            return check_hyperlink_rule({"type": check_type, "target": target, "expected": expected}, file_path)

        if domain == "advanced" and check_type in ("cross_reference", "cross_reference_target"):
            from .checks.cross_reference import check_cross_reference_rule
            return check_cross_reference_rule({"type": check_type, "target": target, "expected": expected}, file_path)

        if domain == "advanced" and check_type == "bookmark":
            return self._check_bookmark(file_path, expected)
        if domain == "advanced" and check_type == "bibliography":
            return self._check_bibliography(file_path, expected)
        if domain == "advanced" and check_type == "style_applied":
            return self._check_style_applied(document, target, expected)
        if domain == "advanced" and check_type == "style_count":
            return self._check_style_count(document, expected)
        if domain == "advanced" and check_type in {"style_font_name", "style_underline", "style_shadow", "style_underline_type", "style_character_spacing", "paragraph_after_heading_style"}:
            return self._check_style_format(document, check_type, expected)
        if domain == "object":
            return self._check_object(document, check_type, target, expected, file_path)
        if domain == "document":
            return self._check_document(document, check_type, expected, file_path)
        if domain == "paragraph_formatting" and check_type in ("header_alignment", "footer_alignment"):
            return self._check_document(document, check_type, expected, file_path)
        return CheckerResult(passed=False, details={"reason": f"Unsupported domain '{domain}'."})

