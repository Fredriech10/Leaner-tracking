import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}


EXPECTED_NARROW_MARGIN = "720"
EXPECTED_LETTER_W = "12240"
EXPECTED_LETTER_H = "15840"


@dataclass
class CheckResult:
    status: str
    awarded: int | float | str
    reason: str


def normalize_text(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("'", "")
    value = re.sub(r"\s+", " ", value)
    return value


def split_name_parts(folder_name: str) -> List[str]:
    if "_T2_12RR" in folder_name.upper():
        rr_base = re.sub(r"_T2_12RR[23]$", "", folder_name, flags=re.I).strip()
        rr_parts = [part.strip() for part in rr_base.split("_") if part.strip()]
        pieces: List[str] = []
        for part in rr_parts:
            spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", part)
            for token in spaced.split():
                token = normalize_text(token)
                if token:
                    pieces.append(token)
        return pieces

    base = folder_name.split("(", 1)[0].strip()
    raw_parts = [part.strip() for part in base.split(".") if part.strip()]
    pieces: List[str] = []
    for part in raw_parts:
        spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", part)
        for token in spaced.split():
            token = normalize_text(token)
            if token:
                pieces.append(token)
    return pieces


class Q2Document:
    def __init__(self, path: Path, learner_name: str):
        self.path = path
        self.learner_name = learner_name
        self.exists = path.exists()
        self.errors: List[str] = []

        self.margins: Dict[str, str] = {}
        self.page_width = ""
        self.page_height = ""

        self.header_texts: List[str] = []
        self.header_has_any_text = False
        self.header_has_date_field = False
        self.header_date_format_ok = False
        self.header_has_tabs_before_date = False
        self.header_has_right_separation = False

        self.heading2_texts: List[str] = []
        self.do_list_num_id = ""
        self.dont_list_num_id = ""
        self.do_list_count = 0
        self.dont_list_count = 0
        self.numbering_formats: Dict[str, Dict[str, str]] = {}

        self.intro_heading_index = -1
        self.toc_before_intro = False
        self.toc_instr = ""
        self.toc_has_two_levels = False
        self._toc_candidates: List[tuple[int, str]] = []
        self.toc_entry_count = 0
        self.toc_has_dot_leader_entries = False
        self.toc_has_toc_styles = False
        self.toc_level1_entries: List[str] = []

        self.picture_has_crop = False
        self.picture_wrap_tight = False
        self.picture_has_effect_style = False
        self.picture_fits_layout = False
        self.picture_alt_text = ""
        self.picture_has_caption = False

        if self.exists:
            try:
                self._load()
            except Exception as exc:  # pragma: no cover
                self.errors.append(f"Q2 parse error: {exc}")
        else:
            self.errors.append("Q2 file not found")

    def _load(self) -> None:
        with zipfile.ZipFile(self.path) as zf:
            doc = ET.fromstring(zf.read("word/document.xml"))
            self._load_section_properties(doc)
            self._load_headers(zf, doc)
            self._load_numbering(zf)
            self._load_paragraph_structure(doc)
            self._load_drawings(doc)

    def _load_section_properties(self, doc: ET.Element) -> None:
        sect = doc.find(".//w:sectPr", NS)
        if sect is None:
            return
        pg_mar = sect.find("w:pgMar", NS)
        if pg_mar is not None:
            self.margins = {k.split("}", 1)[1]: v for k, v in pg_mar.attrib.items()}
        pg_sz = sect.find("w:pgSz", NS)
        if pg_sz is not None:
            self.page_width = pg_sz.attrib.get(f"{{{NS['w']}}}w", "")
            self.page_height = pg_sz.attrib.get(f"{{{NS['w']}}}h", "")

    def _load_headers(self, zf: zipfile.ZipFile, doc: ET.Element) -> None:
        sect = doc.find(".//w:sectPr", NS)
        if sect is None:
            return
        hdr_refs = sect.findall("w:headerReference", NS)
        if not hdr_refs or "word/_rels/document.xml.rels" not in zf.namelist():
            return

        rels = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        for href in hdr_refs:
            rid = href.attrib.get(f"{{{NS['r']}}}id", "")
            target = relmap.get(rid, "")
            if not target:
                continue
            header_path = "word/" + target
            if header_path not in zf.namelist():
                continue
            header = ET.fromstring(zf.read(header_path))
            for para in header.findall(".//w:p", NS):
                text = "".join(t.text or "" for t in para.findall(".//w:t", NS)).strip()
                if text:
                    self.header_texts.append(text)
                    self.header_has_any_text = True
                instr = "".join(t.text or "" for t in para.findall(".//w:instrText", NS))
                if "DATE" in instr.upper():
                    self.header_has_date_field = True
                    self.header_date_format_ok = 'dd/mmm/yyyy' in instr
                    runs = para.findall("w:r", NS)
                    date_field_index = -1
                    for idx, run in enumerate(runs):
                        if run.find("w:instrText", NS) is not None:
                            date_field_index = idx
                            break
                    if date_field_index > 0:
                        tab_count = 0
                        for run in runs[:date_field_index]:
                            tab_count += len(run.findall("w:tab", NS))
                        self.header_has_tabs_before_date = tab_count >= 1
                ppr = para.find("w:pPr", NS)
                if ppr is not None:
                    tabs = ppr.findall("w:tabs/w:tab", NS)
                    if any(tab.attrib.get(f"{{{NS['w']}}}val", "") == "right" for tab in tabs):
                        self.header_has_right_separation = True
                    jc = ppr.find("w:jc", NS)
                    if jc is not None and jc.attrib.get(f"{{{NS['w']}}}val", "") == "right":
                        self.header_has_right_separation = True
                run_tab_count = sum(len(run.findall("w:tab", NS)) for run in para.findall("w:r", NS))
                if run_tab_count >= 1:
                    self.header_has_right_separation = True
                if any(
                    ptab.attrib.get(f"{{{NS['w']}}}alignment", "") == "right"
                    for ptab in para.findall(".//w:ptab", NS)
                ):
                    self.header_has_right_separation = True

    def _load_numbering(self, zf: zipfile.ZipFile) -> None:
        if "word/numbering.xml" not in zf.namelist():
            return
        numbering = ET.fromstring(zf.read("word/numbering.xml"))
        num_to_abs = {
            num.attrib.get(f"{{{NS['w']}}}numId", ""): (
                num.find("w:abstractNumId", NS).attrib.get(f"{{{NS['w']}}}val", "")
                if num.find("w:abstractNumId", NS) is not None
                else ""
            )
            for num in numbering.findall("w:num", NS)
        }
        for num_id, abs_id in num_to_abs.items():
            abstract = numbering.find(f"w:abstractNum[@w:abstractNumId='{abs_id}']", NS)
            if abstract is None:
                continue
            lvl0 = abstract.find("w:lvl[@w:ilvl='0']", NS)
            if lvl0 is None:
                continue
            num_fmt = lvl0.find("w:numFmt", NS)
            lvl_text = lvl0.find("w:lvlText", NS)
            fonts = lvl0.find("w:rPr/w:rFonts", NS)
            self.numbering_formats[num_id] = {
                "format": num_fmt.attrib.get(f"{{{NS['w']}}}val", "") if num_fmt is not None else "",
                "text": lvl_text.attrib.get(f"{{{NS['w']}}}val", "") if lvl_text is not None else "",
                "font": fonts.attrib.get(f"{{{NS['w']}}}ascii", "") if fonts is not None else "",
            }

    def _load_paragraph_structure(self, doc: ET.Element) -> None:
        paras = doc.findall(".//w:body//w:p", NS)
        non_empty = []
        for para in paras:
            text = "".join(t.text or "" for t in para.findall(".//w:t", NS)).strip()
            if not text and not para.findall(".//w:instrText", NS):
                continue
            non_empty.append((para, text))

        for idx, (para, text) in enumerate(non_empty):
            pstyle = para.find("w:pPr/w:pStyle", NS)
            style_val = pstyle.attrib.get(f"{{{NS['w']}}}val", "") if pstyle is not None else ""
            if style_val == "Heading2":
                self.heading2_texts.append(text)
            if (
                style_val == "Heading1"
                and "Introduction: Digital Marketing as a Career Opportunity" in text
                and self.intro_heading_index < 0
            ):
                self.intro_heading_index = idx
            instr = "".join(t.text or "" for t in para.findall(".//w:instrText", NS))
            if "TOC" in instr.upper():
                self._toc_candidates.append((idx, instr))
            if style_val == "Caption" or "SEQ Figure" in instr:
                self.picture_has_caption = True

        if self._toc_candidates:
            toc_idx, toc_instr = self._toc_candidates[0]
            self.toc_instr = toc_instr
            self.toc_before_intro = self.intro_heading_index < 0 or toc_idx < self.intro_heading_index
            self.toc_has_two_levels = any(levels in toc_instr for levels in ('1-2', '"1-2"', '1-3', '"1-3"'))

        in_toc = False
        for para, text in non_empty:
            pstyle = para.find("w:pPr/w:pStyle", NS)
            style_val = pstyle.attrib.get(f"{{{NS['w']}}}val", "") if pstyle is not None else ""
            instr = "".join(t.text or "" for t in para.findall(".//w:instrText", NS))
            if "TOC" in instr.upper():
                in_toc = True
            if in_toc and (style_val.startswith("TOC") or "PAGEREF" in instr.upper() or "TOC" in instr.upper()):
                if style_val.startswith("TOC"):
                    self.toc_has_toc_styles = True
                if style_val in {"TOC1", "TOC2"}:
                    self.toc_entry_count += 1
                if style_val == "TOC1" and text:
                    self.toc_level1_entries.append(text)
                tabs = para.findall("w:pPr/w:tabs/w:tab", NS)
                if any(
                    tab.attrib.get(f"{{{NS['w']}}}val", "") == "right"
                    and tab.attrib.get(f"{{{NS['w']}}}leader", "") == "dot"
                    for tab in tabs
                ):
                    self.toc_has_dot_leader_entries = True
            elif in_toc and style_val == "Heading1":
                break

        for idx, (_, text) in enumerate(non_empty):
            if normalize_text(text) == "do:":
                self.do_list_num_id, self.do_list_count = self._count_following_list(non_empty, idx)
            if normalize_text(text) == "dont:":
                self.dont_list_num_id, self.dont_list_count = self._count_following_list(non_empty, idx)

    def _count_following_list(self, non_empty: List[tuple[ET.Element, str]], heading_idx: int) -> tuple[str, int]:
        count = 0
        num_id = ""
        for para, text in non_empty[heading_idx + 1:]:
            pstyle = para.find("w:pPr/w:pStyle", NS)
            style_val = pstyle.attrib.get(f"{{{NS['w']}}}val", "") if pstyle is not None else ""
            if style_val.startswith("Heading"):
                break
            num_pr = para.find("w:pPr/w:numPr", NS)
            if num_pr is None:
                if count:
                    break
                continue
            para_num_id = num_pr.find("w:numId", NS)
            if para_num_id is None:
                continue
            current_num_id = para_num_id.attrib.get(f"{{{NS['w']}}}val", "")
            if not num_id:
                num_id = current_num_id
            if current_num_id != num_id:
                break
            count += 1
        return num_id, count

    def _load_drawings(self, doc: ET.Element) -> None:
        page_width = int(self.page_width) if self.page_width.isdigit() else 0
        for drawing in doc.findall(".//w:drawing", NS):
            anchor = drawing.find("wp:anchor", NS)
            inline = drawing.find("wp:inline", NS)
            container = anchor if anchor is not None else inline
            if container is None:
                continue
            pic = drawing.find(".//pic:pic", NS)
            if pic is None:
                continue
            src_rect = pic.find(".//a:srcRect", NS)
            if src_rect is not None:
                self.picture_has_crop = True
            if anchor is not None and anchor.find("wp:wrapTight", NS) is not None:
                self.picture_wrap_tight = True
            effect = pic.find(".//a:effectLst", NS)
            geom = pic.find(".//a:prstGeom", NS)
            if effect is not None or (geom is not None and geom.attrib.get("prst") not in {"rect", ""}):
                self.picture_has_effect_style = True
            doc_pr = container.find("wp:docPr", NS)
            if doc_pr is not None:
                self.picture_alt_text = doc_pr.attrib.get("descr", "") or doc_pr.attrib.get("title", "")
            extent = container.find("wp:extent", NS)
            if extent is not None and page_width:
                cx = int(extent.attrib.get("cx", "0"))
                self.picture_fits_layout = cx <= 4500000


def evaluate_q2_check(doc: Q2Document, check: Dict) -> CheckResult:
    if not doc.exists:
        return CheckResult("manual", "", "Q2 file missing")
    if doc.errors:
        return CheckResult("manual", "", "; ".join(doc.errors))

    desc = check["description"]
    mark = check["mark"]

    def pass_fail(ok: bool, ok_reason: str, fail_reason: str) -> CheckResult:
        return CheckResult("pass" if ok else "fail", mark if ok else 0, ok_reason if ok else fail_reason)

    learner_name_tokens = split_name_parts(doc.learner_name)
    header_norm = normalize_text(" ".join(doc.header_texts))
    header_has_name = bool(header_norm) and all(part in header_norm for part in learner_name_tokens)

    mapping = {
        "set to ‘Narrow’ margin": lambda: pass_fail(
            all(doc.margins.get(side) == EXPECTED_NARROW_MARGIN for side in ("top", "right", "bottom", "left")),
            "Page margins are set to Narrow",
            f"Page margins are {doc.margins!r}",
        ),
        "changed to Letter": lambda: pass_fail(
            doc.page_width == EXPECTED_LETTER_W and doc.page_height == EXPECTED_LETTER_H,
            "Page size is Letter",
            f"Page size is {doc.page_width} x {doc.page_height}",
        ),
        "your name and surname added": lambda: pass_fail(
            header_has_name,
            "Header contains the learner name and surname",
            f"Header text is {doc.header_texts!r}",
        ),
        "name and surname left aligned": lambda: pass_fail(
            header_has_name,
            "Header name block is present and defaults to left alignment",
            f"Header name block not detected: {doc.header_texts!r}",
        ),
        "current date in the format dd/mmm/yyyy.": lambda: pass_fail(
            doc.header_date_format_ok,
            "Header contains a DATE field with dd/mmm/yyyy format",
            "Header DATE field format dd/mmm/yyyy not detected",
        ),
        "date on the right-hand side": lambda: pass_fail(
            doc.header_has_right_separation,
            "Header date appears separated to the right",
            "Header date does not appear separated to the right",
        ),
        "date will automatically update": lambda: pass_fail(
            doc.header_has_date_field,
            "Header contains an automatic DATE field",
            "Automatic DATE field not detected in header",
        ),
        "Heading 2 style applied to the text ‘Do’ and ‘Don’t’": lambda: pass_fail(
            normalize_text("do:") in {normalize_text(x) for x in doc.heading2_texts}
            and any(normalize_text(x) == "dont:" for x in doc.heading2_texts),
            "Both Do and Don’t use Heading 2",
            f"Heading 2 texts are {doc.heading2_texts!r}",
        ),
        "bullet structured list under Do bullets -": lambda: pass_fail(
            doc.do_list_count >= 5,
            f"Detected {doc.do_list_count} bullet items under Do",
            f"Detected only {doc.do_list_count} bullet items under Do",
        ),
        "\"Do\" list symbol Webdings, character code 97": lambda: pass_fail(
            doc.numbering_formats.get(doc.do_list_num_id, {}).get("font") == "Webdings"
            and doc.numbering_formats.get(doc.do_list_num_id, {}).get("text") == "\uf061",
            "Do list uses Webdings bullet 97",
            f"Do list numbering format is {doc.numbering_formats.get(doc.do_list_num_id, {})!r}",
        ),
        "bullet structured list under Don’t": lambda: pass_fail(
            doc.dont_list_count >= 5,
            f"Detected {doc.dont_list_count} bullet items under Don’t",
            f"Detected only {doc.dont_list_count} bullet items under Don’t",
        ),
        "\"Don't\" list symbol Webdings, character code 114": lambda: pass_fail(
            doc.numbering_formats.get(doc.dont_list_num_id, {}).get("font") == "Webdings"
            and doc.numbering_formats.get(doc.dont_list_num_id, {}).get("text") == "\uf072",
            "Don’t list uses Webdings bullet 114",
            f"Don’t list numbering format is {doc.numbering_formats.get(doc.dont_list_num_id, {})!r}",
        ),
        "inserted above the heading ‘Introduction: Digital Marketing as a Career Opportunity’": lambda: pass_fail(
            doc.toc_before_intro,
            "TOC field is present before the Introduction heading",
            "TOC field not detected before the Introduction heading",
        ),
        "Of Formal template": lambda: pass_fail(
            (
                doc.toc_has_toc_styles
                and doc.toc_has_dot_leader_entries
                and doc.toc_entry_count >= 2
                and bool(doc.toc_level1_entries)
                and all(
                    any(ch.isalpha() for ch in entry) and entry.upper() == entry
                    for entry in doc.toc_level1_entries
                )
            ),
            "TOC formatting matches a Formal-style pattern",
            (
                f"TOC formatting pattern not detected: "
                f"styles={doc.toc_has_toc_styles}, dot_leaders={doc.toc_has_dot_leader_entries}, "
                f"entries={doc.toc_entry_count}, all_caps={all(any(ch.isalpha() for ch in entry) and entry.upper() == entry for entry in doc.toc_level1_entries) if doc.toc_level1_entries else False}"
            ),
        ),
        "2 levels": lambda: pass_fail(
            doc.toc_has_two_levels,
            "TOC field requests 2 levels",
            f"TOC field does not show 2 levels: {doc.toc_instr!r}",
        ),
        "image cropped": lambda: pass_fail(
            doc.picture_has_crop,
            "Detected picture crop settings",
            "Picture crop settings not detected",
        ),
        "focus on the main subject": lambda: pass_fail(
            doc.picture_has_crop,
            "Detected picture crop settings",
            "Picture crop settings not detected",
        ),
        "appropriate picture style applied": lambda: pass_fail(
            doc.picture_has_effect_style,
            "Detected picture style/effect geometry",
            "Picture style/effect geometry not detected",
        ),
        "text wrap as ‘Tight’  neatly next to the text": lambda: pass_fail(
            doc.picture_wrap_tight,
            "Detected Tight text wrap on the picture",
            "Tight text wrap not detected on the picture",
        ),
        "image fits within the page layout": lambda: pass_fail(
            doc.picture_fits_layout,
            "Picture size appears to fit within the page layout",
            "Picture size appears too large for the page layout",
        ),
        "descriptive Caption added": lambda: pass_fail(
            doc.picture_has_caption,
            "Picture has a caption",
            "Picture caption not detected",
        ),
        "descriptive Alt Text added": lambda: pass_fail(
            doc.picture_has_caption,
            "Picture has a caption",
            "Picture caption not detected",
        ),
    }

    if desc in mapping:
        return mapping[desc]()
    return CheckResult("manual", "", f"Q2 actual checker not implemented for {desc}")
