from __future__ import annotations

import argparse
import csv
import json
import os
import re
import urllib.request
from pathlib import Path

from PIL import Image

try:
    import pythoncom
    import win32com.client
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"pywin32 is required for this script: {exc}")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
VBA_EXPORTER = SCRIPT_DIR / "word_icon_exporter.bas"
BERT_IMAGEMSO_LIST_URL = "https://bert-toolkit.com/imagemso-list.html"


IMAGE_MSO_ALIASES = {
    "AccountingNumberFormat": ["AccountingFormat", "FormatCellsDialog"],
    "AllowEditRanges": ["ReviewAllowUsersToEditRanges", "ProtectSheet"],
    "CalculationOptions": ["CalculationOptionsMenu", "CalculateNow"],
    "BordersGallery": ["BordersAll", "BorderOutside", "BorderBottom"],
    "BreaksGallery": ["PageBreakInsertOrRemove", "PageBreakInsert"],
    "CellsDeleteMenu": ["CellsDelete", "DeleteCells"],
    "CellsFormatMenu": ["FormatCellsDialog", "CellsFormat"],
    "CellsInsertMenu": ["CellsInsertDialog", "InsertDialog", "TableRowsOrColumnsOrCellsInsert"],
    "ChartInsertColumn": ["Chart3DColumnChart", "ChartInsert", "GroupInsertChartsExcel"],
    "ChartInsertHierarchy": ["ChartInsert", "GroupInsertChartsExcel"],
    "ChartInsertLine": ["ChartInsert", "ChartAreaChart", "ControlLine"],
    "ChartInsertPie": ["Chart3DPieChart", "ChartInsert"],
    "ChartInsertScatter": ["ChartRadarChart", "ChartInsert"],
    "ChartInsertStatistic": ["ChartInsert", "GroupInsertChartsExcel"],
    "ChartInsertWaterfall": ["ChartInsert", "GroupInsertChartsExcel"],
    "ClearFilter": ["FilterClearAllFilters", "SortClear", "AdvancedFilterDialog", "Clear"],
    "ClearMenu": ["Clear", "ClearFormats"],
    "ComAddIns": ["ComAddInsDialog", "AddIns"],
    "ConditionalFormattingMenu": ["ConditionalFormatting"],
    "ControlInsert": ["FormControlButton"],
    "CreateNamesFromSelection": ["NameCreateFromSelection", "NameDefine"],
    "DateTimeFunctions": ["FunctionsDateTimeInsertGallery", "DateAndTimeInsert"],
    "DefineName": ["NameDefine", "NameDefineMenu", "NameManager"],
    "DeleteComment": ["ReviewDeleteComment"],
    "EvaluateFormula": ["FormulaEvaluate", "ShowFormulas"],
    "ExcelAddIns": ["AddInsDialog", "AddInManager"],
    "ExistingConnections": ["GetExternalDataExistingConnections", "Connections"],
    "FillMenu": ["FillDown", "FillRight"],
    "FinancialFunctions": ["FunctionsFinancialInsertGallery", "FormulaMoreFunctionsMenu"],
    "FindSelectMenu": ["FindDialog"],
    "FlashFill": ["FillMenu", "FillDown"],
    "FontSizeDecrease": ["FontSizeDecreaseExcel", "FontSizeDecrease1Point"],
    "FontSizeIncrease": ["FontSizeIncreaseExcel", "FontSizeIncrease1Point"],
    "ForecastSheet": ["PropertySheet", "SheetBackground"],
    "FreezePanes": ["FreezePanesMenu"],
    "GetData": ["GetExternalDataFromOtherSources", "DataImport"],
    "GetDataFromTable": ["TableInsert", "DataFormSource", "GetExternalDataFromOtherSources"],
    "GetDataFromText": ["TextFromFileInsert", "GetExternalDataFromOtherSources"],
    "GetDataFromWeb": ["GetExternalDataFromWeb", "GetExternalDataFromOtherSources"],
    "GridlinesPrintExcel": ["GridlinesGallery", "ViewSheetGridlines"],
    "GridlinesViewExcel": ["ViewSheetGridlines", "GridlinesGallery"],
    "GroupRowsColumns": ["Grouping", "ObjectsGroup"],
    "HeadingsPrintExcel": ["ViewNormalViewExcel", "PrintSetupDialog"],
    "HeadingsViewExcel": ["ViewNormalViewExcel", "ViewSheetGridlines"],
    "InkLassoSelect": ["ObjectsSelect", "SelectAll"],
    "InkPensGallery": ["InkColorPicker", "PenComment"],
    "InkToMath": ["EquationInsertNew", "InkColorPicker"],
    "InkToShape": ["ShapesInsertGallery", "InkColorPicker"],
    "InsertFunction": ["FunctionWizard"],
    "LogicalFunctions": ["FunctionsLogicalInsertGallery", "FormulaMoreFunctionsMenu"],
    "LookupReferenceFunctions": ["FunctionsLookupReferenceInsertGallery", "FormulaMoreFunctionsMenu"],
    "Macros": ["MacroPlay", "VisualBasic"],
    "MathTrigFunctions": ["FunctionsMathTrigInsertGallery", "FormulaMoreFunctionsMenu"],
    "MergeAndCenter": ["MergeCellsAcross", "MergeOrSplitCells", "AlignCenter"],
    "MoreFunctions": ["FormulaMoreFunctionsMenu", "FunctionsInformationInsertGallery"],
    "NameManager": ["NameManagerDialog"],
    "NextComment": ["ReviewNextComment", "ReviewNextCommentWord"],
    "NextNote": ["ReviewNextComment", "NewNote"],
    "ObjectInsert": ["OleObjectctInsert", "ObjectEditDialog", "InsertDialog"],
    "ObjectsAlignMenu": ["ObjectsAlignLeft", "ObjectsAlignCenterHorizontal"],
    "ObjectsGroupMenu": ["ObjectsGroup"],
    "OfficeAddIns": ["AddInManager", "AddInsDialog"],
    "OfficeAddInsDialog": ["AddInsDialog", "AddInManager"],
    "PageOrientationGallery": ["PageOrientationPortraitLandscape"],
    "PivotTableInsert": ["PivotTableInsertDialog"],
    "PreviousComment": ["ReviewPreviousComment", "ReviewPreviousCommentWord"],
    "PreviousNote": ["ReviewPreviousComment", "NewNote"],
    "PrintAreaMenu": ["PrintAreaSetPrintArea"],
    "ProtectSheet": ["SheetProtect", "ProtectDocument"],
    "ProtectWorkbook": ["ReviewProtectWorkbook", "SheetProtect"],
    "QueriesConnections": ["Connections", "GetExternalDataExistingConnections"],
    "ReapplyFilter": ["FilterReapply", "ApplyFilter", "Filter"],
    "RecentSources": ["RecentFileList", "GetExternalDataFromOtherSources"],
    "RecentlyUsedFunctions": ["FunctionsRecentlyUsedtInsertGallery", "FormulaMoreFunctionsMenu"],
    "RecommendedCharts": ["ChartInsert", "ChartStylesGallery"],
    "RecommendedPivotTables": ["PivotTableReport", "PivotTableInsert"],
    "RecordMacro": ["MacroRecord", "MacroPlay"],
    "Relationships": ["DatabaseRelationships", "RelationshipsDirectRelationships"],
    "RemoveArrows": ["TraceRemoveArrowsMenu", "TraceRemoveAllArrows"],
    "ShowHideNote": ["NewNote", "ReviewShowAllComments"],
    "SortFilterMenu": ["SortAscending", "Filter"],
    "SparklineColumn": ["Chart3DColumnChart", "ColumnWidth"],
    "SparklineLine": ["ControlLine", "ChartAreaChart"],
    "SparklineWinLoss": ["ChartInsert", "ChartAreaChart"],
    "Subtotal": ["OutlineSubtotals", "PivotSubtotal"],
    "TableInsert": ["TableInsertDialog"],
    "TextFunctions": ["FunctionsTextInsertGallery", "FormulaMoreFunctionsMenu"],
    "TextToColumns": ["TextToOrFromTable", "ColumnsDialog"],
    "UngroupRowsColumns": ["OutlineUngroup", "ObjectsUngroup"],
    "UseInFormula": ["NameUseInFormula", "FormulaMoreFunctionsMenu"],
    "UseRelativeReferences": ["MacroRelativeReferences", "VisualBasicReferences"],
    "ViewGridlinesExcel": ["ViewSheetGridlines", "GridlinesGallery"],
    "ViewHeadingsExcel": ["ViewNormalViewExcel", "ViewSheetGridlines"],
    "ViewMacros": ["MacroPlay", "VisualBasic"],
    "ViewRuler": ["RulerShowHide", "ViewRulerPowerPoint"],
    "VisualBasic": ["VisualBasicEditor"],
    "WhatIfAnalysis": ["WhatIfAnalysisMenu", "FormulaEvaluate"],
    "WindowArrangeAll": ["WindowsArrangeAll"],
    "WindowSynchronousScrolling": ["WindowSideBySideSynchronousScrolling", "ViewSideBySide"],
    "WindowViewSideBySide": ["WindowSideBySide", "ViewSideBySide"],
    "XmlExpansionPacks": ["XmlExpansionPacksExcel"],
    "XmlRefreshData": ["Refresh", "RefreshAll"],
    "Zoom100Percent": ["Zoom100"],
}


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def extract_ids_from_layout(filename: Path):
    with open(filename, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    ids = set()

    def walk(value):
        if isinstance(value, dict):
            id_mso = clean(value.get("idMso"))
            image = clean(value.get("image"))
            if id_mso and image:
                ids.add(id_mso)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return sorted(ids)


class ExcelVbaIconExporter:
    def __init__(self, size: int = 128):
        self.size = size
        self.excel = None
        self.workbook = None

    def __enter__(self):
        if not VBA_EXPORTER.exists():
            raise FileNotFoundError(f"VBA exporter not found: {VBA_EXPORTER}")

        pythoncom.CoInitialize()
        self.excel = win32com.client.DispatchEx("Excel.Application")
        self.excel.Visible = False
        self.excel.DisplayAlerts = False
        self.workbook = self.excel.Workbooks.Add()
        try:
            self.workbook.VBProject.VBComponents.Import(str(VBA_EXPORTER))
        except Exception as exc:
            raise RuntimeError(
                "Could not import VBA exporter. Enable 'Trust access to the VBA project object model' "
                "in Excel Trust Center, then rerun the harvester."
            ) from exc
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.workbook is not None:
            try:
                self.workbook.Close(False)
            except Exception:
                pass
        if self.excel is not None:
            try:
                self.excel.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()

    def label(self, id_mso: str):
        return clean(self.excel.CommandBars.GetLabelMso(id_mso))

    def save(self, id_mso: str, output_path: Path):
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        macro = f"'{self.workbook.Name}'!ExportImageMso"
        ok = self.excel.Run(macro, id_mso, str(output_path), int(self.size))
        return bool(ok) and output_path.exists()

    def last_error(self):
        macro = f"'{self.workbook.Name}'!GetLastExportImageMsoError"
        return clean(self.excel.Run(macro))


def save_png_from_bitmap(bmp_path: Path, png_path: Path):
    with Image.open(bmp_path) as img:
        img.convert("RGBA").save(png_path, format="PNG")


def harvest_ids_via_vba(ids, output_dir: Path, size: int = 128):
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    with ExcelVbaIconExporter(size=size) as exporter:
        for index, id_mso in enumerate(ids, start=1):
            print(f"[excel vba {index}/{len(ids)}] {id_mso}")
            label = ""
            try:
                label = exporter.label(id_mso)
            except Exception as exc:
                print(f"  LABEL_UNAVAILABLE: {exc}")

            bmp_path = output_dir / f"{id_mso}.bmp"
            png_path = output_dir / f"{id_mso}.png"
            candidates = [id_mso] + IMAGE_MSO_ALIASES.get(id_mso, [])

            for image_mso in candidates:
                try:
                    if exporter.save(image_mso, bmp_path):
                        if not label:
                            try:
                                label = exporter.label(image_mso)
                            except Exception:
                                label = id_mso
                        save_png_from_bitmap(bmp_path, png_path)
                        rows.append({
                            "idMso": id_mso,
                            "Label": label,
                            "BitmapPath": str(bmp_path),
                            "PngPath": str(png_path),
                            "Source": f"Local Excel VBA GetImageMso:{image_mso}",
                        })
                        if image_mso == id_mso:
                            print(f"  OK: saved {png_path.name}")
                        else:
                            print(f"  OK: saved {png_path.name} via {image_mso}")
                        break
                except Exception as exc:
                    print(f"  SAVE_FAILED {image_mso}: {exc}")
                else:
                    error = exporter.last_error()
                    if error:
                        print(f"  SAVE_FAILED {image_mso}: {error}")
            else:
                print("  NO FILE CREATED")

    return rows


def discover_public_names():
    html = urllib.request.urlopen(BERT_IMAGEMSO_LIST_URL, timeout=30).read().decode("utf-8", errors="replace")
    return set(re.findall(r"<a name=([^>\s]+)>", html))


def write_csv(path: Path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["idMso", "Label", "BitmapPath", "PngPath", "Source"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Excel 2021 icon harvester")
    parser.add_argument("--ids", type=str, default="", help="Comma-separated IDs to test")
    parser.add_argument("--size", type=int, default=128, help="Icon size to request from Excel")
    parser.add_argument("--layout", type=str, default=str(PROJECT_ROOT / "Practical" / "Layout" / "excel2021_ribbon_layout_full.json"))
    parser.add_argument("--output", type=str, default=str(PROJECT_ROOT / "Practical" / "Images" / "Excel"))
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    ids = [p.strip() for p in args.ids.split(",") if p.strip()] if args.ids else extract_ids_from_layout(Path(args.layout))

    print("Starting Excel icon harvest...")
    rows = harvest_ids_via_vba(ids, output_dir, size=args.size)
    write_csv(output_dir / "excel_icons.csv", rows)

    print()
    print(f"Saved {len(rows)} valid icons to {output_dir}")
    print("Most important file:")
    print(output_dir / "excel_icons.csv")


if __name__ == "__main__":
    main()
