"""Reusable openpyxl checks for no-code Excel practical tasks."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import re

from openpyxl import load_workbook

from .checker_types import BaseChecker, CheckerResult


class ExcelChecker(BaseChecker):
    program = "excel"

    def check(self, domain: str, check_type: str, target: Dict[str, Any], expected: Any, file_path: Path) -> CheckerResult:
        try:
            workbook = load_workbook(file_path, data_only=False)
        except Exception as exc:
            return CheckerResult(False, details={"reason": f"Could not read workbook: {exc}"})
        try:
            sheet_name = str((target or {}).get("sheet", ""))
            sheet = workbook[sheet_name] if sheet_name and sheet_name in workbook.sheetnames else workbook.active
            cell_ref = str((target or {}).get("cell", ""))
            cell = sheet[cell_ref] if cell_ref else None
            wanted = str(expected or "").strip()
            actual: Any = None
            passed = False
            if check_type == "worksheet_exists":
                actual = workbook.sheetnames
                passed = wanted.casefold() in {name.casefold() for name in workbook.sheetnames}
            elif check_type == "worksheet_name":
                actual = sheet.title
                passed = actual.casefold() == wanted.casefold()
            elif check_type == "cell_value":
                actual = cell.value if cell else None
                passed = str(actual or "").strip().casefold() == wanted.casefold()
            elif check_type == "cell_contains":
                actual = cell.value if cell else None
                passed = wanted.casefold() in str(actual or "").casefold()
            elif check_type == "formula_contains":
                actual = cell.value if cell else None
                passed = isinstance(actual, str) and actual.startswith("=") and wanted.casefold() in actual.casefold()
            elif check_type == "formula_exact":
                actual = cell.value if cell else None
                passed = isinstance(actual, str) and actual.casefold().replace(" ", "") == wanted.casefold().replace(" ", "")
            elif check_type == "formula_references":
                actual = cell.value if cell else None
                references = [value.strip().casefold() for value in wanted.split(",") if value.strip()]
                passed = isinstance(actual, str) and actual.startswith("=") and all(value in actual.casefold() for value in references)
            elif check_type == "number_format":
                actual = cell.number_format if cell else None
                passed = wanted.casefold() in str(actual or "").casefold()
            elif check_type == "font_name":
                actual = cell.font.name if cell else None
                passed = str(actual or "").casefold() == wanted.casefold()
            elif check_type == "font_bold":
                actual = bool(cell.font.bold) if cell else False
                passed = actual == (wanted.casefold() in {"true", "yes", "1"})
            elif check_type == "font_italic":
                actual = bool(cell.font.italic) if cell else False
                passed = actual == (wanted.casefold() in {"true", "yes", "1"})
            elif check_type == "font_underline":
                actual = bool(cell.font.underline) if cell else False
                passed = actual == (wanted.casefold() in {"true", "yes", "1"})
            elif check_type == "font_color":
                color = cell.font.color if cell else None
                actual = str(getattr(color, "rgb", "") or "")
                passed = wanted.replace("#", "").casefold() in actual.casefold()
            elif check_type == "font_size":
                actual = cell.font.sz if cell else None
                passed = actual is not None and abs(float(actual) - float(expected)) < 0.01
            elif check_type == "fill_color":
                actual = cell.fill.fgColor.rgb if cell else None
                actual = str(actual or "").replace("00", "", 1).casefold()
                passed = wanted.replace("#", "").casefold() in actual
            elif check_type == "border_side":
                side, separator, style = wanted.partition(":")
                side = side.casefold() if separator else "bottom"
                style = style if separator else wanted
                border = getattr(cell.border, side, None) if cell else None
                actual = str(getattr(border, "style", "") or "")
                passed = actual.casefold() == style.casefold()
            elif check_type == "alignment":
                actual = cell.alignment.horizontal if cell else None
                passed = str(actual or "").casefold() == wanted.casefold()
            elif check_type == "vertical_alignment":
                actual = cell.alignment.vertical if cell else None
                passed = str(actual or "").casefold() == wanted.casefold()
            elif check_type == "wrap_text":
                actual = bool(cell.alignment.wrap_text) if cell else False
                passed = actual == (wanted.casefold() in {"true", "yes", "1"})
            elif check_type == "text_rotation":
                actual = cell.alignment.textRotation if cell else None
                passed = actual is not None and int(actual) == int(expected)
            elif check_type == "indent":
                actual = cell.alignment.indent if cell else None
                passed = actual is not None and abs(float(actual) - float(expected)) < 0.01
            elif check_type == "decimal_places":
                actual = cell.number_format if cell else ""
                fraction = str(actual).split(".", 1)[1].split(";", 1)[0] if "." in str(actual) else ""
                decimals = len(re.findall(r"[0#?]", fraction))
                passed = decimals == int(expected)
            elif check_type == "number_format_kind":
                actual = cell.number_format if cell else ""
                formats = str(actual).casefold()
                markers = {"currency": ("r", "$", "€", "[$"), "percentage": ("%",), "date": ("d", "m", "y")}
                passed = all(marker in formats for marker in markers.get(wanted.casefold(), (wanted.casefold(),)))
            elif check_type == "column_width":
                column = cell.column_letter if cell else cell_ref
                actual = sheet.column_dimensions[column].width
                passed = actual is not None and float(actual) >= float(expected)
            elif check_type == "row_height":
                row = cell.row if cell else int(cell_ref)
                actual = sheet.row_dimensions[row].height
                passed = actual is not None and float(actual) >= float(expected)
            elif check_type == "freeze_panes":
                actual = str(sheet.freeze_panes or "")
                passed = actual.casefold() == wanted.casefold()
            elif check_type == "merged_range":
                actual = [str(item) for item in sheet.merged_cells.ranges]
                passed = wanted.casefold() in {item.casefold() for item in actual}
            elif check_type == "sheet_tab_color":
                color = sheet.sheet_properties.tabColor
                actual = str(getattr(color, "rgb", "") or "")
                passed = wanted.replace("#", "").casefold() in actual.casefold()
            elif check_type == "sheet_last":
                actual = workbook.sheetnames[-1]
                passed = actual.casefold() == wanted.casefold()
            elif check_type == "table_style":
                styles = [table.tableStyleInfo.name for table in sheet.tables.values() if table.tableStyleInfo]
                actual = styles
                passed = wanted.casefold() in {style.casefold() for style in styles}
            elif check_type == "sorted_range":
                # Expected: "A2:A50 ascending" or "B2:B50 descending".
                parts = wanted.split()
                range_ref = parts[0] if parts else ""
                direction = parts[1].casefold() if len(parts) > 1 else "ascending"
                cells = [item for row in sheet[range_ref] for item in row] if ":" in range_ref else []
                values = [item.value for item in cells if item.value not in (None, "")]
                comparable = [str(value).casefold() if isinstance(value, str) else value for value in values]
                actual = comparable
                passed = len(comparable) > 1 and comparable == sorted(comparable, reverse=direction == "descending")
            elif check_type == "conditional_formatting_present":
                actual = len(sheet.conditional_formatting)
                passed = actual > 0
            elif check_type == "conditional_formatting_range":
                actual = [str(item) for item in sheet.conditional_formatting]
                normalised_expected = wanted.replace("$", "").casefold()
                passed = any(normalised_expected in item.replace("$", "").casefold() for item in actual)
            elif check_type == "image_at_cell":
                anchors = []
                for image in sheet._images:
                    anchor = getattr(image, "anchor", None)
                    marker = getattr(anchor, "_from", None)
                    if marker is not None:
                        anchors.append(f"{chr(65 + marker.col)}{marker.row + 1}")
                actual = anchors
                passed = wanted.casefold() in {item.casefold() for item in anchors}
            elif check_type == "chart_title":
                titles = [str(getattr(chart.title, "tx", "") or "") for chart in sheet._charts]
                actual = titles
                passed = any(wanted.casefold() in title.casefold() for title in titles)
            elif check_type == "page_orientation":
                actual = str(sheet.page_setup.orientation or "")
                passed = actual.casefold() == wanted.casefold()
            elif check_type == "fit_to_page":
                actual = (sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight)
                passed = str(actual[0]) == wanted or (wanted.casefold() == "enabled" and actual[0] is not None)
            elif check_type == "chart_count":
                actual = len(sheet._charts)
                passed = actual >= int(expected)
            elif check_type == "table_present":
                actual = list(sheet.tables)
                passed = bool(actual)
            return CheckerResult(passed, actual, {"type": check_type, "target": target, "expected": expected})
        finally:
            workbook.close()
