from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    import pythoncom
    import win32com.client as win32
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "This program requires pywin32. Install it with: pip install pywin32"
    ) from exc


TASK_FILES = {
    "word": "1Diamonds.docx",
    "excel": "2Diamonds Data.xlsx",
    "access": "3Diamond Sales.accdb",
    "html": "4Diamonds_Insights.html",
}


@dataclass
class MarkResult:
    section: str
    item: str
    description: str
    max_mark: int
    mark_awarded: int
    passed: bool
    evidence: str


class MarkerError(RuntimeError):
    pass


def com_retry(action: Callable[[], Any], attempts: int = 8, delay: float = 0.5) -> Any:
    """Retry Office calls briefly while a desktop application is busy."""
    for attempt in range(attempts):
        try:
            return action()
        except pythoncom.com_error as exc:
            if getattr(exc, "hresult", None) != -2147418111 or attempt == attempts - 1:
                raise
            time.sleep(delay)


class ComApp:
    def __init__(self, prog_id: str):
        self.prog_id = prog_id
        self.app = None

    def __enter__(self):
        pythoncom.CoInitialize()
        # DispatchEx isolates this run from documents a teacher may have open.
        self.app = win32.DispatchEx(self.prog_id)
        # Learner files are inspection-only: prevent startup macros or events from
        # performing actions such as printing while Office opens the submission.
        try:
            self.app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        except Exception:
            pass
        try:
            self.app.EnableEvents = False
        except Exception:
            pass
        return self.app

    def __exit__(self, exc_type, exc, tb):
        if self.app is not None:
            try:
                com_retry(self.app.Quit)
            except Exception:
                pass
        pythoncom.CoUninitialize()


def normalise_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def safe_call(func: Callable[[], MarkResult], section: str, item: str, description: str, max_mark: int) -> MarkResult:
    try:
        return func()
    except Exception as exc:
        return MarkResult(
            section=section,
            item=item,
            description=description,
            max_mark=max_mark,
            mark_awarded=0,
            passed=False,
            evidence=f"Check failed: {exc}",
        )


def find_submission_files(submission_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in submission_dir.iterdir():
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".docx" and "word" not in files:
            files["word"] = path
        elif suffix == ".xlsx" and "excel" not in files:
            files["excel"] = path
        elif suffix == ".accdb" and "access" not in files:
            files["access"] = path
        elif suffix in {".html", ".htm"} and "html" not in files:
            files["html"] = path
    missing = [name for name in TASK_FILES if name not in files]
    if missing:
        raise MarkerError(
            f"Submission folder is missing expected file types: {', '.join(missing)}"
        )
    return files


class WordMarker:
    def __init__(self, document_path: Path):
        self.document_path = document_path

    def mark(self) -> list[MarkResult]:
        results: list[MarkResult] = []
        with ComApp("Word.Application") as word:
            word.Visible = False
            doc = com_retry(lambda: word.Documents.Open(str(self.document_path.resolve()), ReadOnly=True))
            try:
                results.extend(self._mark_document(doc))
            finally:
                com_retry(lambda: doc.Close(False))
        return results

    def _mark_document(self, doc: Any) -> list[MarkResult]:
        return [
            safe_call(lambda: self._check_endnote_conversion(doc), "Q1", "1.1", "Footnote converted to endnote with Webdings 126 symbol", 2),
            safe_call(lambda: self._check_subheading_style(doc), "Q1", "1.2", "Subheading style created correctly", 4),
            safe_call(lambda: self._check_bibliography(doc), "Q1", "1.3", "Source and automatic bibliography inserted", 3),
            safe_call(lambda: self._check_toc(doc), "Q1", "1.4", "Automatic 2-level table of contents above Introduction", 3),
        ]

    def _check_endnote_conversion(self, doc: Any) -> MarkResult:
        footnotes = doc.Footnotes.Count
        endnotes = doc.Endnotes.Count
        mark = 0
        evidence: list[str] = [f"footnotes={footnotes}", f"endnotes={endnotes}"]

        if footnotes == 0 and endnotes >= 1:
            mark += 1

        symbol_ok = False
        if endnotes >= 1:
            note = doc.Endnotes(1)
            ref_text = normalise_text(note.Reference.Text)
            ref_font = normalise_text(note.Reference.Font.Name)
            symbol_ok = ref_font.lower() == "webdings" or ref_text in {"~", "126", "\x02"}
            evidence.append(f"reference_font={ref_font or 'unknown'}")
            evidence.append(f"reference_text={ref_text or 'blank'}")
        if symbol_ok:
            mark += 1

        return MarkResult("Q1", "1.1", "Footnote converted to endnote with Webdings 126 symbol", 2, mark, mark == 2, "; ".join(evidence))

    def _check_subheading_style(self, doc: Any) -> MarkResult:
        style = None
        for item in doc.Styles:
            if normalise_text(item.NameLocal).lower() == "subheading":
                style = item
                break
        if style is None:
            return MarkResult("Q1", "1.2", "Subheading style created correctly", 4, 0, False, "Style 'Subheading' not found")

        mark = 1
        evidence = ["style_found=True"]
        base_style = normalise_text(getattr(style, "BaseStyle", ""))
        if base_style.lower() == "heading 2":
            mark += 1
        evidence.append(f"base_style_ok={base_style.lower() == 'heading 2'}")

        colour = getattr(style.Font, "Color", None)
        if colour in {8388608, 128, 16711680, 6299648, -553582593}:  # Word can expose dark blue in multiple ways
            mark += 1
        evidence.append(f"dark_blue_ok={colour in {8388608, 128, 16711680, 6299648, -553582593}}")

        if int(getattr(style.Font, "Size", 0)) == 12:
            mark += 1
        evidence.append(f"font_size_12_ok={int(getattr(style.Font, 'Size', 0)) == 12}")

        return MarkResult("Q1", "1.2", "Subheading style created correctly", 4, mark, mark == 4, "; ".join(evidence))

    def _check_bibliography(self, doc: Any) -> MarkResult:
        mark = 0
        evidence: list[str] = []

        bibliography_fields = [field for field in doc.Fields if field.Type == 97]  # wdFieldBibliography
        bibliography_text = " ".join(normalise_text(field.Result.Text) for field in bibliography_fields).lower()
        source_found = False
        for source in doc.Bibliography.Sources:
            tag_text = " ".join(
                normalise_text(getattr(source, attr, ""))
                for attr in ("Tag", "Title", "Author", "Year", "Publisher", "URL", "XML")
            ).lower()
            compact = re.sub(r"[^a-z0-9]", "", tag_text)
            if "debeer" in compact and "annual" in compact and "2025" in compact:
                source_found = True
                evidence.append("Source matched De Beers Annual Report 2025 using tolerant spelling")
                break
        if not source_found:
            compact_bibliography = re.sub(r"[^a-z0-9]", "", bibliography_text)
            source_found = "debeer" in compact_bibliography and "annual" in compact_bibliography and "2025" in compact_bibliography
            if source_found:
                evidence.append("Source matched in the updated bibliography using tolerant spelling")
        if source_found and bibliography_fields:
            mark += 1
        else:
            evidence.append("Required source not found")

        bibliography_at_bottom = any(field.Result.Start >= doc.Content.End * 0.6 for field in bibliography_fields)
        if bibliography_at_bottom:
            mark += 1
        evidence.append(f"bibliography_at_bottom={bibliography_at_bottom}")

        bibliography_updated = bool(bibliography_fields) and all(
            normalise_text(field.Result.Text) and "error!" not in normalise_text(field.Result.Text).lower()
            for field in bibliography_fields
        )
        if bibliography_updated:
            mark += 1
        evidence.append(f"bibliography_field={bool(bibliography_fields)}; bibliography_updated={bibliography_updated}")

        return MarkResult("Q1", "1.3", "Source and automatic bibliography inserted", 3, mark, mark == 3, "; ".join(evidence))

    def _check_toc(self, doc: Any) -> MarkResult:
        mark = 0
        evidence: list[str] = []

        toc_count = doc.TablesOfContents.Count
        if toc_count >= 1:
            mark += 1
        evidence.append(f"toc_count={toc_count}")

        intro_pos = doc.Content.Text.lower().find("introduction")
        toc_ok = False
        levels_ok = False
        if toc_count >= 1:
            toc = doc.TablesOfContents(1)
            toc_pos = int(toc.Range.Start)
            evidence.append(f"toc_start={toc_pos}")
            if intro_pos >= 0:
                intro_range = doc.Range(0, doc.Content.End).Text.lower().find("introduction")
                toc_ok = toc_pos <= max(intro_range, 0)
            else:
                toc_ok = True
            if toc_ok:
                mark += 1
            levels_ok = int(toc.LowerHeadingLevel) == 2
            if levels_ok:
                mark += 1
        evidence.append(f"toc_before_intro={toc_ok}")
        evidence.append(f"toc_lower_heading_level={getattr(doc.TablesOfContents(1), 'LowerHeadingLevel', 'n/a') if toc_count else 'n/a'}")

        return MarkResult("Q1", "1.4", "Automatic 2-level table of contents above Introduction", 3, mark, mark == 3, "; ".join(evidence))


class ExcelMarker:
    def __init__(self, workbook_path: Path, submission_dir: Path):
        self.workbook_path = workbook_path
        self.submission_dir = submission_dir

    def mark(self) -> list[MarkResult]:
        results: list[MarkResult] = []
        with ComApp("Excel.Application") as excel:
            excel.Visible = False
            excel.DisplayAlerts = False
            workbook = com_retry(lambda: excel.Workbooks.Open(str(self.workbook_path.resolve()), ReadOnly=True))
            try:
                results.extend(self._mark_workbook(workbook))
            finally:
                com_retry(lambda: workbook.Close(False))
        return results

    def _mark_workbook(self, workbook: Any) -> list[MarkResult]:
        return [
            safe_call(lambda: self._check_currency_format(workbook), "Q2", "2.1", "Price per Carat formatted as rand/currency", 1),
            safe_call(lambda: self._check_conditional_format(workbook), "Q2", "2.2", "Conditional formatting for Colour Code contains F with green fill", 3),
            safe_call(lambda: self._check_freeze_panes(workbook), "Q2", "2.3", "Freeze panes keeps headings and first 3 columns visible", 2),
            safe_call(lambda: self._check_summary_formula(workbook), "Q2", "2.4", "Summary!B2 totals Base Price from Investors", 3),
            safe_call(lambda: self._check_print_setup(workbook), "Q2", "2.5", "Print setup and PDF export completed", 6),
        ]

    def _ws(self, workbook: Any, name: str) -> Any:
        return workbook.Worksheets(name)

    def _find_header_column(self, ws: Any, header_name: str, row: int = 1) -> int:
        used = ws.UsedRange
        for column in range(1, used.Columns.Count + 1):
            value = normalise_text(ws.Cells(row, column).Value)
            if value.lower() == header_name.lower():
                return column
        raise MarkerError(f"Header '{header_name}' not found on sheet '{ws.Name}'")

    def _check_currency_format(self, workbook: Any) -> MarkResult:
        ws = self._ws(workbook, "Investors")
        col = self._find_header_column(ws, "Price per Carat")
        fmt = normalise_text(ws.Cells(2, col).NumberFormat)
        passed = any(token in fmt for token in ("R", "[$R", "Currency", "#,##0.00"))
        return MarkResult("Q2", "2.1", "Price per Carat formatted as rand/currency", 1, 1 if passed else 0, passed, f"number_format={fmt}")

    def _check_conditional_format(self, workbook: Any) -> MarkResult:
        ws = self._ws(workbook, "Investors")
        col = self._find_header_column(ws, "Colour Code")
        last_row = ws.UsedRange.Rows.Count
        data_range = ws.Range(ws.Cells(2, col), ws.Cells(last_row, col))
        mark = 0
        evidence = [f"range={data_range.Address}"]

        if data_range.FormatConditions.Count >= 1:
            mark += 1
            matched = False
            green_fill = False
            for idx in range(1, data_range.FormatConditions.Count + 1):
                fc = data_range.FormatConditions(idx)
                formula1 = normalise_text(getattr(fc, "Formula1", ""))
                if "F" in formula1.upper() or "CONTAIN" in formula1.upper():
                    matched = True
                    fill = getattr(fc.Interior, "Color", None)
                    if fill in {5287936, 5296274, 65280}:
                        green_fill = True
                    evidence.append(f"formula={formula1}")
                    evidence.append(f"fill={fill}")
                    break
            if matched:
                mark += 1
            if green_fill:
                mark += 1

        return MarkResult("Q2", "2.2", "Conditional formatting for Colour Code contains F with green fill", 3, mark, mark == 3, "; ".join(evidence))

    def _check_freeze_panes(self, workbook: Any) -> MarkResult:
        window = workbook.Windows(1)
        mark = 0
        split_row = int(getattr(window, "SplitRow", 0))
        split_col = int(getattr(window, "SplitColumn", 0))
        freeze = bool(getattr(window, "FreezePanes", False))
        if freeze:
            mark += 1
        if split_row >= 1 and split_col >= 3:
            mark += 1
        return MarkResult("Q2", "2.3", "Freeze panes keeps headings and first 3 columns visible", 2, mark, mark == 2, f"freeze={freeze}; split_row={split_row}; split_col={split_col}")

    def _check_summary_formula(self, workbook: Any) -> MarkResult:
        ws = self._ws(workbook, "Summary")
        formula = normalise_text(ws.Range("B2").Formula)
        value = ws.Range("B2").Value
        mark = 0
        if formula.startswith("="):
            mark += 1
        if "SUM" in formula.upper():
            mark += 1
        if "INVESTORS" in formula.upper():
            mark += 1
        return MarkResult("Q2", "2.4", "Summary!B2 totals Base Price from Investors", 3, mark, mark == 3, f"formula={formula}; value={value}")

    def _check_print_setup(self, workbook: Any) -> MarkResult:
        ws = self._ws(workbook, "Investors")
        setup = ws.PageSetup
        mark = 0
        evidence: list[str] = []

        print_area = normalise_text(setup.PrintArea)
        print_area_ok = "$A$1:$K$101" in print_area.upper()
        if print_area_ok:
            mark += 1
        evidence.append(f"print_area_ok={print_area_ok}")

        title_rows = normalise_text(setup.PrintTitleRows)
        title_rows_ok = "$1:$1" in title_rows
        if title_rows_ok:
            mark += 1
        evidence.append(f"title_rows_ok={title_rows_ok}")

        landscape_ok = int(setup.Orientation) == 2
        if landscape_ok:
            mark += 1
        evidence.append(f"landscape_ok={landscape_ok}")

        fit_columns_ok = int(setup.Zoom) in {False, 0} and int(setup.FitToPagesWide) == 1
        if fit_columns_ok:
            mark += 1
        evidence.append(f"fit_columns_ok={fit_columns_ok}")

        pdf_paths = [path for path in self.submission_dir.glob("*.pdf") if "invest" in path.stem.lower()]
        pdf_exists = bool(pdf_paths)
        pdf_name_ok = any(path.name.lower() == "investors.pdf" for path in pdf_paths)
        if pdf_exists:
            mark += 1
        if pdf_name_ok:
            mark += 1
        evidence.append(f"pdf_exists={pdf_exists}; pdf_name_ok={pdf_name_ok}")

        return MarkResult("Q2", "2.5", "Print setup and PDF export completed", 6, mark, mark == 6, "; ".join(evidence))


class AccessMarker:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def mark(self) -> list[MarkResult]:
        results: list[MarkResult] = []
        with ComApp("Access.Application") as access:
            access.Visible = False
            com_retry(lambda: access.OpenCurrentDatabase(str(self.database_path.resolve())))
            try:
                results.extend(self._mark_database(access))
            finally:
                com_retry(access.CloseCurrentDatabase)
        return results

    def _get_field_property(self, field: Any, name: str, default: Any = "") -> Any:
        try:
            return field.Properties(name).Value
        except Exception:
            return default

    def _mark_database(self, access: Any) -> list[MarkResult]:
        db = access.CurrentDb()
        table = db.TableDefs("tblDiamonds")
        return [
            safe_call(lambda: self._check_diamond_id_field(table), "Q3", "3.1.1", "DiamondID field size 6 and required", 2),
            safe_call(lambda: self._check_input_mask(table), "Q3", "3.1.2", "DiamondID input mask 1 required letter followed by 4 digits", 2),
            safe_call(lambda: self._check_default_value(table), "Q3", "3.1.3", "StockStatus default value set to Sold", 1),
            safe_call(lambda: self._check_report_fields(access), "Q3", "3.2.1", "Report includes required fields in order", 2),
            safe_call(lambda: self._check_report_group(access), "Q3", "3.2.2", "Report grouped by StockStatus", 1),
            safe_call(lambda: self._check_report_sort(access), "Q3", "3.2.3", "Report sorted by DiamondID ascending", 2),
            safe_call(lambda: self._check_report_layout(access), "Q3", "3.2.4", "Report uses tabular layout and landscape orientation", 2),
            self._check_report_exists(access),
            safe_call(lambda: self._check_report_heading(access), "Q3", "3.3.1", "Report displays the specified heading", 1),
            safe_call(lambda: self._check_report_visibility(access), "Q3", "3.3.2", "Report fields and labels are fully visible", 1),
        ]

    def _check_diamond_id_field(self, table: Any) -> MarkResult:
        field = table.Fields("DiamondID")
        mark = 0
        field_type = int(getattr(field, "Type", -1))
        size = int(getattr(field, "Size", 0))
        required = bool(getattr(field, "Required", False))
        size_ok = field_type == 10 and size == 6  # dbText: input masks require a text field.
        if size_ok:
            mark += 1
        if required:
            mark += 1
        return MarkResult("Q3", "3.1.1", "DiamondID field size 6 and required", 2, mark, mark == 2, f"size_ok={size_ok}; required_ok={required}; type={field_type}; size={size}")

    def _check_input_mask(self, table: Any) -> MarkResult:
        field = table.Fields("DiamondID")
        mask = normalise_text(self._get_field_property(field, "InputMask"))
        mark = 0
        if any(token in mask.upper() for token in ("L0000", ">L0000", "A0000")):
            mark += 1
        if "0000" in mask:
            mark += 1
        return MarkResult("Q3", "3.1.2", "DiamondID input mask 1 required letter followed by 4 digits", 2, mark, mark == 2, f"input_mask={mask}")

    def _check_default_value(self, table: Any) -> MarkResult:
        field = table.Fields("StockStatus")
        default = normalise_text(self._get_field_property(field, "DefaultValue")).strip("\"'")
        passed = default.lower() == "sold"
        return MarkResult("Q3", "3.1.3", "StockStatus default value set to Sold", 1, 1 if passed else 0, passed, f"default_value={default}")

    def _check_report_fields(self, access: Any) -> MarkResult:
        report_name = "rptDiamondSummary"
        if report_name not in [doc.Name for doc in access.CurrentProject.AllReports]:
            return MarkResult("Q3", "3.2.1", "Report includes required fields in order", 2, 0, False, "Report not found")
        text = self._report_text(access)
        required = ["DiamondID", "Carat", "CutCode", "ColourCode", "ClarityCode", "PriceZAR", "StockStatus"]
        positions = [text.find(f'ControlSource ="{name}"') for name in required]
        included = all(position >= 0 for position in positions)
        return MarkResult("Q3", "3.2.1", "Report includes required fields in order", 2, 2 if included else 0, included, f"static_report_export; positions={positions}")

    def _report_text(self, access: Any) -> str:
        path = Path(tempfile.gettempdir()) / f"cat_report_{id(self)}.txt"
        try:
            access.SaveAsText(3, "rptDiamondSummary", str(path))  # acReport; never opens the report window.
            return path.read_text(encoding="utf-16", errors="ignore")
        finally:
            path.unlink(missing_ok=True)

    def _check_report_group(self, access: Any) -> MarkResult:
        text = self._report_text(access)
        passed = "GroupHeader = NotDefault" in text and 'ControlSource ="StockStatus"' in text
        return MarkResult("Q3", "3.2.2", "Report grouped by StockStatus", 1, int(passed), passed, "static_report_export")

    def _check_report_sort(self, access: Any) -> MarkResult:
        text = self._report_text(access)
        source = text.find('ControlSource ="DiamondID"')
        passed = source >= 0 and source < text.find('Name ="Detail"')
        return MarkResult("Q3", "3.2.3", "Report sorted by DiamondID ascending", 2, 2 if passed else 0, passed, "static_report_export")

    def _check_report_layout(self, access: Any) -> MarkResult:
        # The task specifies Access's default tabular layout.  Landscape is verified
        # from a temporary rendered PDF rather than opening the report or decoding
        # printer-driver-specific binary settings.
        report_name = "rptDiamondSummary"
        report_exists = report_name in [doc.Name for doc in access.CurrentProject.AllReports]
        if not report_exists:
            return MarkResult(
                "Q3", "3.2.4", "Report uses tabular layout and landscape orientation",
                2, 0, False, "tabular_ok=False; landscape_ok=False; Report not found",
            )
        landscape_ok, evidence = self._report_pdf_is_landscape(access)
        mark = 1 + int(landscape_ok)
        return MarkResult(
            "Q3", "3.2.4", "Report uses tabular layout and landscape orientation",
            2, mark, mark == 2,
            f"tabular_ok=True; landscape_ok={landscape_ok}; {evidence}",
        )

    def _report_pdf_is_landscape(self, access: Any) -> tuple[bool, str]:
        report_name = "rptDiamondSummary"
        if report_name not in [doc.Name for doc in access.CurrentProject.AllReports]:
            return False, "Report not found"

        pdf_path = Path(tempfile.gettempdir()) / f"cat_landscape_{id(self)}.pdf"
        try:
            pdf_path.unlink(missing_ok=True)
            # acOutputReport, PDF export. This creates a temporary file only; it
            # does not invoke a printer or open the report in preview/design view.
            access.DoCmd.OutputTo(3, report_name, "PDF Format (*.pdf)", str(pdf_path), False)
            data = pdf_path.read_bytes()
            boxes = re.findall(
                rb"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]",
                data,
            )
            if not boxes:
                return False, "temporary_pdf_export; page_size_not_found"
            widths = [float(right) - float(left) for left, _bottom, right, _top in boxes]
            heights = [float(top) - float(bottom) for left, bottom, _right, top in boxes]
            landscape = all(width > height for width, height in zip(widths, heights))
            return landscape, (
                "temporary_pdf_export; "
                f"pages={len(boxes)}; first_page={widths[0]:.2f}x{heights[0]:.2f}; "
                f"all_pages_landscape={landscape}"
            )
        finally:
            pdf_path.unlink(missing_ok=True)

    def _check_report_heading(self, access: Any) -> MarkResult:
        text = self._report_text(access).upper()
        passed = 'CAPTION ="DIAMOND STOCK AND VALUE SUMMARY"' in text
        return MarkResult("Q3", "3.3.1", "Report displays the specified heading", 1, int(passed), passed, "static_report_export")

    def _check_report_visibility(self, access: Any) -> MarkResult:
        text = self._report_text(access)
        required = ["DiamondID", "Carat", "CutCode", "ColourCode", "ClarityCode", "PriceZAR", "StockStatus"]
        passed = all(f'Caption ="{name}"' in text for name in required)
        return MarkResult("Q3", "3.3.2", "Report fields and labels are fully visible", 1, int(passed), passed, "static_report_export")

    def _report_not_opened(self, item: str, description: str, maximum: int) -> MarkResult:
        return MarkResult(
            "Q3", item, description, maximum, 0, False,
            "Not inspected: Access reports are never opened by the marker to prevent print actions",
        )

    def _check_report_exists(self, access: Any) -> MarkResult:
        report_name = "rptDiamondSummary"
        if report_name not in [doc.Name for doc in access.CurrentProject.AllReports]:
            return MarkResult("Q3", "3.2.5", "Report saved as rptDiamondSummary", 1, 0, False, "Report not found")
        return MarkResult("Q3", "3.2.5", "Report saved as rptDiamondSummary", 1, 1, True, "Report exists; report body was not opened")


class HtmlMarker:
    def __init__(self, html_path: Path):
        self.html_path = html_path

    def mark(self) -> list[MarkResult]:
        html_text = self.html_path.read_text(encoding="utf-8", errors="ignore")
        doc = win32.Dispatch("htmlfile")
        doc.write(html_text)
        doc.close()
        return [
            safe_call(lambda: self._check_body_colour(doc), "Q4", "4.1.1", "Body background colour set to #F4F0E6", 1),
            safe_call(lambda: self._check_ordered_list(doc), "Q4", "4.1.2", "Ordered list uses capital letters", 2),
            safe_call(lambda: self._check_image(doc), "Q4", "4.1.3", "Image uses correct src and alt text", 2),
            safe_call(lambda: self._check_link(doc), "Q4", "4.1.4", "Hyperlink points to GIA page with correct text", 2),
            safe_call(lambda: self._check_tag_syntax(html_text), "Q4", "4.1.5", "Correct tag and angle bracket usage", 1),
        ]

    def _check_body_colour(self, doc: Any) -> MarkResult:
        body = doc.getElementsByTagName("body")
        if body.length == 0:
            return MarkResult("Q4", "4.1.1", "Body background colour set to #F4F0E6", 1, 0, False, "No <body> tag found")
        node = body.item(0)
        colour = normalise_text(getattr(node, "bgColor", "") or getattr(node.style, "backgroundColor", ""))
        passed = colour.lower() in {"#f4f0e6", "f4f0e6", "rgb(244, 240, 230)"}
        return MarkResult("Q4", "4.1.1", "Body background colour set to #F4F0E6", 1, 1 if passed else 0, passed, f"body_colour={colour}")

    def _check_ordered_list(self, doc: Any) -> MarkResult:
        ols = doc.getElementsByTagName("ol")
        if ols.length == 0:
            return MarkResult("Q4", "4.1.2", "Ordered list uses capital letters", 2, 0, False, "No <ol> tag found")
        ol = ols.item(0)
        ol_type = normalise_text(getattr(ol, "type", ""))
        item_count = ol.getElementsByTagName("li").length
        mark = int(ol_type.upper() == "A") + int(item_count >= 4)
        return MarkResult("Q4", "4.1.2", "Ordered list uses capital letters", 2, mark, mark == 2, f"type={ol_type}; item_count={item_count}")

    def _check_image(self, doc: Any) -> MarkResult:
        imgs = doc.getElementsByTagName("img")
        if imgs.length == 0:
            return MarkResult("Q4", "4.1.3", "Image uses correct src and alt text", 2, 0, False, "No <img> tag found")
        img = imgs.item(0)
        src = normalise_text(getattr(img, "src", ""))
        alt = normalise_text(getattr(img, "alt", ""))
        src_ok = src.lower().endswith("diamond_insights.png")
        alt_ok = alt == "Faceted diamond - Diamonds Insights" or alt == "Faceted diamond – Diamonds Insights"
        mark = int(src_ok) + int(alt_ok)
        return MarkResult("Q4", "4.1.3", "Image uses correct src and alt text", 2, mark, mark == 2, f"src_ok={src_ok}; alt_ok={alt_ok}; src={src}; alt={alt}")

    def _check_link(self, doc: Any) -> MarkResult:
        links = doc.getElementsByTagName("a")
        if links.length == 0:
            return MarkResult("Q4", "4.1.4", "Hyperlink points to GIA page with correct text", 2, 0, False, "No hyperlink found")
        link = links.item(0)
        href = normalise_text(getattr(link, "href", ""))
        text = normalise_text(getattr(link, "innerText", ""))
        mark = int("gia.edu/diamond-education" in href.lower()) + int(text == "GIA Diamond Education")
        return MarkResult("Q4", "4.1.4", "Hyperlink points to GIA page with correct text", 2, mark, mark == 2, f"href={href}; text={text}")

    def _check_tag_syntax(self, html_text: str) -> MarkResult:
        opens = html_text.count("<")
        closes = html_text.count(">")
        passed = opens == closes and "</html>" in html_text.lower()
        return MarkResult("Q4", "4.1.5", "Correct tag and angle bracket usage", 1, 1 if passed else 0, passed, f"open_brackets={opens}; close_brackets={closes}")


def write_reports(results: Iterable[MarkResult], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = list(results)
    csv_path = output_dir / "mark_report.csv"
    json_path = output_dir / "mark_report.json"

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for item in results:
            writer.writerow(asdict(item))

    summary = {
        "results": [asdict(item) for item in results],
        "total_awarded": sum(item.mark_awarded for item in results),
        "total_possible": sum(item.max_mark for item in results),
    }
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return csv_path, json_path


def print_summary(results: Iterable[MarkResult]) -> None:
    results = list(results)
    awarded = sum(item.mark_awarded for item in results)
    possible = sum(item.max_mark for item in results)
    print(f"Total: {awarded}/{possible}")
    for item in results:
        status = "PASS" if item.passed else "FAIL"
        print(f"{item.section} {item.item}: {item.mark_awarded}/{item.max_mark} {status} - {item.description}")


def run(submission_dir: Path, output_dir: Path) -> int:
    files = find_submission_files(submission_dir)
    results: list[MarkResult] = []
    results.extend(WordMarker(files["word"]).mark())
    results.extend(ExcelMarker(files["excel"], submission_dir).mark())
    results.extend(AccessMarker(files["access"]).mark())
    results.extend(HtmlMarker(files["html"]).mark())
    csv_path, json_path = write_reports(results, output_dir)
    print_summary(results)
    print(f"CSV report: {csv_path}")
    print(f"JSON report: {json_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="COM-based auto marker for the Grade 11 CAT diamonds task."
    )
    parser.add_argument(
        "submission_dir",
        nargs="?",
        default="Original Data",
        help="Folder containing the student's Word, Excel, Access, HTML and PDF files.",
    )
    parser.add_argument(
        "--output-dir",
        default="mark_output",
        help="Folder where the CSV and JSON reports will be written.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    submission_dir = Path(args.submission_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not submission_dir.exists():
        print(f"Submission folder not found: {submission_dir}", file=sys.stderr)
        return 2

    try:
        return run(submission_dir, output_dir)
    except Exception as exc:
        print(f"Auto marker failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
