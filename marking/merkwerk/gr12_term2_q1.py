import math
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


EXPECTED_DOC_COMMENT = "This document is about the origin of digital marketing"
EXPECTED_DOC_SUBJECT = "1Digital Marketing"
EXPECTED_FOOTNOTE_TEXT = "The use of digital technologies and online platforms to promote products or services"
EXPECTED_TOTAL_LABEL = "Total possible Income ="
DEFAULT_COVER_FILL_SIGNATURE = ("scheme:tx2", "scheme:bg1", "scheme:bg2")


@dataclass
class CheckResult:
    status: str
    awarded: int | float | str
    reason: str


def normalize_text(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[.]+$", "", lowered)
    lowered = lowered.replace("’", "'").replace("‘", "'").replace('"', "")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered


def levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            ))
        prev = curr
    return prev[-1]


class Q1Document:
    def __init__(self, path: Path):
        self.path = path
        self.exists = path.exists()
        self.errors: List[str] = []
        self.core_subject = ""
        self.core_description = ""
        self.blip_count = 0
        self.cover_fill_signature: tuple[str, ...] = ()
        self.do_not_hyphenate_caps = False
        self.subtitle_alias_present = False
        self.strong_style_fonts: set[str] = set()
        self.strong_style_spacing: Optional[str] = None
        self.strong_style_underline: Optional[str] = None
        self.introduction_para_uses_strong = False
        self.mobile_marketing_has_footnote = False
        self.mobile_marketing_footnote_symbol_font = ""
        self.mobile_marketing_footnote_symbol_char = ""
        self._footnote_symbols_by_id: Dict[str, tuple[str, str]] = {}
        self.footnote_texts: List[str] = []
        self.five_column_section_present = False
        self.five_column_space_correct = False
        self.heading2_process_count = 0
        self.column_break_count = 0
        self.table_header_shaded = False
        self.table_channel_entries_italic = False
        self.table_extra_row_present = False
        self.table_last_row_merge_present = False
        self.table_total_label_present = False
        self.table_total_label_text = ""
        self.table_total_value_correct = False
        self.table_sorted_alpha = False

        if self.exists:
            try:
                self._load()
            except Exception as exc:  # pragma: no cover - defensive
                self.errors.append(f"Q1 parse error: {exc}")
        else:
            self.errors.append("Q1 file not found")

    def _load(self) -> None:
        with zipfile.ZipFile(self.path) as zf:
            self._load_core(zf)
            self._load_settings(zf)
            doc = ET.fromstring(zf.read("word/document.xml"))
            self.blip_count = len(doc.findall(".//a:blip", NS))
            self._load_cover_fill_signature(doc)
            self._load_sdts(doc)
            self._load_styles(zf)
            self._load_intro_paragraph(doc)
            self._load_footnotes(zf, doc)
            self._load_columns(doc)
            self._load_table(doc)

    def _load_cover_fill_signature(self, doc: ET.Element) -> None:
        fills: List[str] = []
        for fill in doc.findall(".//a:solidFill", NS):
            srgb = fill.find("a:srgbClr", NS)
            scheme = fill.find("a:schemeClr", NS)
            if srgb is not None:
                fills.append(f"srgb:{srgb.attrib.get('val', '')}")
            elif scheme is not None:
                fills.append(f"scheme:{scheme.attrib.get('val', '')}")
            else:
                fills.append("other")
        self.cover_fill_signature = tuple(fills)

    def _load_core(self, zf: zipfile.ZipFile) -> None:
        core = ET.fromstring(zf.read("docProps/core.xml"))
        self.core_subject = (core.findtext("dc:subject", "", NS) or "").strip()
        self.core_description = (core.findtext("dc:description", "", NS) or "").strip()

    def _load_settings(self, zf: zipfile.ZipFile) -> None:
        if "word/settings.xml" not in zf.namelist():
            return
        settings = ET.fromstring(zf.read("word/settings.xml"))
        self.do_not_hyphenate_caps = settings.find(".//w:doNotHyphenateCaps", NS) is not None

    def _load_sdts(self, doc: ET.Element) -> None:
        aliases = []
        for sdt in doc.findall(".//w:sdt", NS):
            alias = sdt.find(".//w:alias", NS)
            if alias is not None:
                aliases.append(alias.attrib.get(f"{{{NS['w']}}}val", ""))
        self.subtitle_alias_present = "Subtitle" in aliases

    def _load_styles(self, zf: zipfile.ZipFile) -> None:
        styles = ET.fromstring(zf.read("word/styles.xml"))
        for style in styles.findall("w:style", NS):
            style_id = style.attrib.get(f"{{{NS['w']}}}styleId")
            if style_id == "Strong":
                rpr = style.find("w:rPr", NS)
                if rpr is None:
                    continue
                fonts = rpr.find("w:rFonts", NS)
                if fonts is not None:
                    for key in (f"{{{NS['w']}}}ascii", f"{{{NS['w']}}}hAnsi"):
                        val = fonts.attrib.get(key)
                        if val:
                            self.strong_style_fonts.add(val)
                spacing = rpr.find("w:spacing", NS)
                if spacing is not None:
                    self.strong_style_spacing = spacing.attrib.get(f"{{{NS['w']}}}val")
                underline = rpr.find("w:u", NS)
                if underline is not None:
                    self.strong_style_underline = underline.attrib.get(f"{{{NS['w']}}}val")

    def _paragraph_text(self, paragraph: ET.Element) -> str:
        return "".join(t.text or "" for t in paragraph.findall(".//w:t", NS)).strip()

    def _load_intro_paragraph(self, doc: ET.Element) -> None:
        paragraphs = doc.findall(".//w:body/w:p", NS)
        non_empty = [(p, self._paragraph_text(p)) for p in paragraphs]
        non_empty = [(p, t) for p, t in non_empty if t]
        if len(non_empty) >= 3:
            intro_para = non_empty[2][0]
            self.introduction_para_uses_strong = any(
                rstyle.attrib.get(f"{{{NS['w']}}}val") == "Strong"
                for rstyle in intro_para.findall(".//w:rStyle", NS)
            )

        for p, text in non_empty:
            if text.startswith(("1. Research", "2. Create", "3. Distribute", "4. Analyse", "5. Improve")):
                pstyle = p.find("w:pPr/w:pStyle", NS)
                if pstyle is not None and pstyle.attrib.get(f"{{{NS['w']}}}val") == "Heading2":
                    self.heading2_process_count += 1
            for br in p.findall(".//w:br", NS):
                if br.attrib.get(f"{{{NS['w']}}}type") == "column":
                    self.column_break_count += 1

    def _load_footnotes(self, zf: zipfile.ZipFile, doc: ET.Element) -> None:
        if "word/footnotes.xml" in zf.namelist():
            footnotes = ET.fromstring(zf.read("word/footnotes.xml"))
            self.footnote_texts = [
                "".join(t.text or "" for t in foot.findall(".//w:t", NS)).strip()
                for foot in footnotes.findall("w:footnote", NS)
                if "".join(t.text or "" for t in foot.findall(".//w:t", NS)).strip()
            ]
            for foot in footnotes.findall("w:footnote", NS):
                foot_id = foot.attrib.get(f"{{{NS['w']}}}id", "")
                texts = "".join(t.text or "" for t in foot.findall(".//w:t", NS)).strip()
                if not texts:
                    continue
                for sym_run in foot.findall(".//w:r", NS):
                    sym = sym_run.find("w:sym", NS)
                    if sym is not None and foot_id:
                        self._footnote_symbols_by_id[foot_id] = (
                            sym.attrib.get(f"{{{NS['w']}}}font", ""),
                            sym.attrib.get(f"{{{NS['w']}}}char", ""),
                        )
                        break

        for p in doc.findall(".//w:body/w:p", NS):
            text = self._paragraph_text(p)
            if "mobile marketing" in text.lower():
                footnote_ref = p.find(".//w:footnoteReference", NS)
                if footnote_ref is not None:
                    self.mobile_marketing_has_footnote = True
                    foot_id = footnote_ref.attrib.get(f"{{{NS['w']}}}id", "")
                    symbol = self._footnote_symbols_by_id.get(foot_id)
                    if symbol:
                        self.mobile_marketing_footnote_symbol_font = symbol[0]
                        self.mobile_marketing_footnote_symbol_char = symbol[1]
                break

    def _load_columns(self, doc: ET.Element) -> None:
        for sect in doc.findall(".//w:sectPr", NS):
            cols = sect.find("w:cols", NS)
            if cols is None:
                continue
            num = cols.attrib.get(f"{{{NS['w']}}}num")
            space = cols.attrib.get(f"{{{NS['w']}}}space")
            if num == "5":
                self.five_column_section_present = True
                self.five_column_space_correct = space == "284"

    def _load_table(self, doc: ET.Element) -> None:
        table = doc.find(".//w:tbl", NS)
        if table is None:
            return

        rows = table.findall("w:tr", NS)
        self.table_extra_row_present = len(rows) >= 5
        if not rows:
            return

        header_cells = rows[0].findall("w:tc", NS)
        self.table_header_shaded = all(
            cell.find("w:tcPr/w:shd", NS) is not None for cell in header_cells[:4]
        )

        texts = []
        for row in rows:
            cells = row.findall("w:tc", NS)
            texts.append(
                ["".join(t.text or "" for t in cell.findall(".//w:t", NS)).strip() for cell in cells]
            )

        if len(rows) >= 4:
            channel_ok = True
            for row in rows[1:4]:
                first_cell = row.findall("w:tc", NS)[0]
                if first_cell.find(".//w:i", NS) is None:
                    channel_ok = False
                    break
            self.table_channel_entries_italic = channel_ok

        if self.table_extra_row_present:
            last_row = rows[-1]
            cells = last_row.findall("w:tc", NS)
            self.table_last_row_merge_present = bool(
                cells and cells[0].find("w:tcPr/w:gridSpan", NS) is not None
            )
            last_row_texts = texts[-1]
            self.table_total_label_text = last_row_texts[0] if last_row_texts else ""
            self.table_total_label_present = bool(last_row_texts and "Total possible Income" in last_row_texts[0])
            try:
                incomes = []
                for row_texts in texts[1:-1]:
                    if len(row_texts) >= 4:
                        value = row_texts[3].replace("\xa0", "").replace("R", "").replace(" ", "")
                        incomes.append(float(value))
                final_value = texts[-1][-1].replace("\xa0", "").replace("R", "").replace(" ", "")
                self.table_total_value_correct = math.isclose(sum(incomes), float(final_value), rel_tol=1e-9)
            except Exception:
                self.table_total_value_correct = False

        channel_values = [row[0] for row in texts[1:-1] if row and row[0]]
        self.table_sorted_alpha = channel_values == sorted(channel_values, key=lambda s: s.lower())


def evaluate_q1_check(doc: Q1Document, check: Dict) -> CheckResult:
    if not doc.exists:
        return CheckResult("manual", "", "Q1 file missing")
    if doc.errors:
        return CheckResult("manual", "", "; ".join(doc.errors))

    desc = check["description"]
    mark = check["mark"]
    expected_comment_normalized = normalize_text(EXPECTED_DOC_COMMENT)
    expected_subject_normalized = normalize_text(EXPECTED_DOC_SUBJECT)
    expected_footnote_normalized = normalize_text(EXPECTED_FOOTNOTE_TEXT)
    expected_total_label_normalized = normalize_text(EXPECTED_TOTAL_LABEL)

    def pass_fail(ok: bool, reason_true: str, reason_false: str) -> CheckResult:
        return CheckResult("pass" if ok else "fail", mark if ok else 0, reason_true if ok else reason_false)

    def tolerant_text_match(actual: str, expected_normalized: str, label: str, max_distance: int = 3) -> CheckResult:
        actual = actual.strip()
        if not actual:
            return CheckResult("fail", 0, f"{label} is ''")
        normalized = normalize_text(actual)
        if normalized == expected_normalized:
            return CheckResult("pass", mark, f"{label} matches expected value")
        distance = levenshtein_distance(normalized, expected_normalized)
        if distance <= max_distance:
            return CheckResult(
                "pass",
                mark,
                f"{label} accepted as close attempt (distance {distance}): {actual!r}",
            )
        return CheckResult("fail", 0, f"{label} is {actual!r}")

    def tolerant_comment_match() -> CheckResult:
        return tolerant_text_match(doc.core_description, expected_comment_normalized, "Document comment/description")

    def tolerant_subject_match() -> CheckResult:
        return tolerant_text_match(doc.core_subject, expected_subject_normalized, "Document subject", max_distance=2)

    def tolerant_footnote_text_match() -> CheckResult:
        if not doc.footnote_texts:
            return CheckResult("fail", 0, "Footnote text is ''")
        best = min(
            doc.footnote_texts,
            key=lambda value: levenshtein_distance(normalize_text(value), expected_footnote_normalized),
        )
        return tolerant_text_match(best, expected_footnote_normalized, "Footnote text", max_distance=4)

    def tolerant_total_label_match() -> CheckResult:
        table = getattr(doc, "table_total_label_text", "")
        return tolerant_text_match(table, expected_total_label_normalized, "Final table row total-income label", max_distance=4)

    mapping = {
        "image inserted 1CoverPic.png": lambda: pass_fail(
            doc.blip_count > 0,
            "Detected image content in the document body",
            "No document-body image detected",
        ),
        "recoloured background block to white": lambda: CheckResult(
            "pass" if doc.cover_fill_signature != DEFAULT_COVER_FILL_SIGNATURE else "fail",
            mark if doc.cover_fill_signature != DEFAULT_COVER_FILL_SIGNATURE else 0,
            (
                f"Detected non-default cover fill signature {doc.cover_fill_signature!r}"
                if doc.cover_fill_signature != DEFAULT_COVER_FILL_SIGNATURE
                else f"Cover fill signature still matches default {DEFAULT_COVER_FILL_SIGNATURE!r}"
            ),
        ),
        "removed document subtitle control box": lambda: pass_fail(
            not doc.subtitle_alias_present,
            "Subtitle content control is absent",
            "Subtitle content control is still present",
        ),
        "‘1Digital Marketing' as subject in document property": tolerant_subject_match,
        "‘This document is about the origin of digital marketing’ as comment in document property": tolerant_comment_match,
        "font type to Century Gothic": lambda: pass_fail(
            "Century Gothic" in doc.strong_style_fonts,
            "Strong style uses Century Gothic",
            f"Strong style fonts are {sorted(doc.strong_style_fonts)!r}",
        ),
        "text double underlined": lambda: pass_fail(
            doc.strong_style_underline == "double",
            "Strong style underline is double",
            f"Strong style underline is {doc.strong_style_underline!r}",
        ),
        "character spacing to an expanded spacing of 3 pt": lambda: pass_fail(
            doc.strong_style_spacing == "60",
            "Strong style spacing is 60 twips (3 pt)",
            f"Strong style spacing is {doc.strong_style_spacing!r}",
        ),
        "applied to the paragraph under the heading ‘Introduction’": lambda: pass_fail(
            doc.introduction_para_uses_strong,
            "Paragraph after Introduction uses the Strong style",
            "Paragraph after Introduction does not use the Strong style",
        ),
        "to the text 'mobile marketing'": lambda: pass_fail(
            doc.mobile_marketing_has_footnote,
            "Found a footnote reference on the mobile marketing text",
            "No footnote reference found on the mobile marketing text",
        ),
        "footnote text ‘The use of digital technologies and online platforms to promote products or services.’": tolerant_footnote_text_match,
        "The reference mark Webdings character code: 85 .": lambda: pass_fail(
            doc.mobile_marketing_footnote_symbol_font == "Webdings" and doc.mobile_marketing_footnote_symbol_char == "F055",
            "Mobile marketing footnote uses Webdings F055",
            (
                f"Mobile marketing footnote symbol is "
                f"{doc.mobile_marketing_footnote_symbol_font or 'none'} "
                f"{doc.mobile_marketing_footnote_symbol_char or 'none'}"
            ),
        ),
        "to NOT hyphenate text displayed in capital letters": lambda: pass_fail(
            doc.do_not_hyphenate_caps,
            "Document setting do not hyphenate capitalized words is enabled",
            "Document setting do not hyphenate capitalized words is not enabled",
        ),
        "5 columns": lambda: pass_fail(
            doc.five_column_section_present,
            "Found a 5-column section",
            "No 5-column section found",
        ),
        "Heading to style to the sub-headings": lambda: pass_fail(
            doc.heading2_process_count >= 5,
            f"Detected {doc.heading2_process_count} process subheadings using Heading 2",
            f"Detected only {doc.heading2_process_count} process subheadings using Heading 2",
        ),
        "column breaks before each sub-heading": lambda: pass_fail(
            doc.column_break_count >= 3,
            f"Detected {doc.column_break_count} column breaks in the process section",
            f"Detected only {doc.column_break_count} column breaks in the process section",
        ),
        "space between columns is 0.5 cm": lambda: pass_fail(
            doc.five_column_space_correct,
            "5-column section uses 0.5 cm spacing",
            "5-column section spacing is not 0.5 cm",
        ),
        "first row shaded": lambda: pass_fail(
            doc.table_header_shaded,
            "Table header row is shaded",
            "Table header row shading not detected",
        ),
        "headings under Channel column italics": lambda: pass_fail(
            doc.table_channel_entries_italic,
            "Channel entries are italicised",
            "Channel entries are not all italicised",
        ),
        "extra row added  at the top": lambda: pass_fail(
            doc.table_extra_row_present,
            "Table has an extra total row",
            "Table extra total row not detected",
        ),
        "first three columns merged": lambda: pass_fail(
            doc.table_last_row_merge_present,
            "Final table row has a merged cell across the first columns",
            "Merged first-columns cell not detected in the final table row",
        ),
        "First Row  text ‘Total possible Income =’ inserted": tolerant_total_label_match,
        "formula added to calculate the total possible income": lambda: pass_fail(
            doc.table_total_value_correct,
            "Final table value matches the sum of the income column",
            "Final table value does not match the sum of the income column",
        ),
        "table sorted alphabetically": lambda: pass_fail(
            doc.table_sorted_alpha,
            "Table channel rows are sorted alphabetically",
            "Table channel rows are not sorted alphabetically",
        ),
        "according to the digital marketing channel.": lambda: pass_fail(
            doc.table_sorted_alpha,
            "Table channel rows are sorted alphabetically by channel",
            "Table channel rows are not sorted alphabetically by channel",
        ),
    }

    if desc in mapping:
        return mapping[desc]()
    return CheckResult("manual", "", f"Q1 actual checker not implemented for {desc}")
