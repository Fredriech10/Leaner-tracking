from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
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
    "AddIns": ["AddInManager", "AddInsDialog"],
    "AdvancedFilterOptions": ["SortAndFilterAdvanced", "AdvancedFilterDialog"],
    "AnalyzePerformance": ["DatabaseAnalyzePerformance"],
    "AnalyzeTable": ["DatabaseAnalyzeTable"],
    "Anchoring": ["ControlAdvancedProperties", "PositionFitToWindow"],
    "ApplicationPartsGallery": ["CreateFormInDesignView", "DatabaseInsert"],
    "BackColorPicker": ["ShapeFillColorPicker", "FontAlternateFillBackColorPicker"],
    "BlankForm": ["FormCreate", "CreateFormInDesignView"],
    "BlankReport": ["CreateReportInDesignView", "ReportCreate"],
    "Builder": ["BuildButton", "RunDialog"],
    "ClassModuleInsert": ["CreateClassModule", "ModuleInsert"],
    "CollectDataByEmail": ["MailMergeStart", "SendEmail"],
    "CompactRepairDatabase": ["FileCompactAndRepairDatabase"],
    "ConditionalFormatting": ["FontConditionalFormatting", "ConditionalFormattingMenu"],
    "ControlButton": ["FormControlButton"],
    "ControlChart": ["ChartInsert"],
    "ControlCheckBox": ["FormControlCheckBox"],
    "ControlComboBox": ["FormControlComboBox"],
    "ControlHyperlink": ["HyperlinkInsert"],
    "ControlLabel": ["FormControlLabel"],
    "ControlLayoutRemove": ["ControlLayoutRemove", "ObjectsUngroup"],
    "ControlLayoutStacked": ["ObjectsAlignLeft"],
    "ControlLayoutTabular": ["TableInsert"],
    "ControlListBox": ["FormControlListBox"],
    "ControlMore": ["MoreControlsDialog"],
    "ControlMargins": ["ControlMarginsGallery", "GroupMarginsAndPaddingControlLayout", "SizeToFit"],
    "ControlNavigation": ["RmsNavigationBar", "AccessNavigationOptions", "CreateFormWithMultipleItems"],
    "ControlOptionGroup": ["FormControlGroupBox"],
    "ControlSelect": ["ObjectsSelect"],
    "ControlSubformSubreport": ["SubformMenu"],
    "ControlPadding": ["GroupMarginsAndPaddingControlLayout", "ControlMarginsGallery"],
    "ControlTab": ["ControlTabControl", "ControlPage"],
    "ControlTextBox": ["FormControlEditBox", "TextBoxInsert"],
    "ControlWebBrowser": ["HyperlinkOpen", "WebPagePreview"],
    "ConvertMacrosToVisualBasic": ["MacroConvertMacrosToVisualBasic", "VisualBasic"],
    "DatabaseEncryptWithPassword": ["SetDatabasePassword", "Lock"],
    "DateTimeInsert": ["DateAndTimeInsert"],
    "DeleteLayoutColumn": ["TableDeleteColumns", "TableColumnsDelete"],
    "DeleteLayoutRow": ["TableDeleteRows", "TableRowsDelete"],
    "ExportAccess": ["ExportAccess"],
    "ExportExcel": ["ExportExcel", "PivotExportToExcel"],
    "ExportMore": ["ExportMoreMenu"],
    "ExportText": ["ExportTextFile"],
    "ExportXml": ["ExportXmlFile", "XmlExport"],
    "FieldAddMenu": ["DatasheetNewField", "FieldList"],
    "FieldCurrency": ["AccountingFormat"],
    "FieldDataType": ["DataValidation"],
    "FieldDateTime": ["DateAndTimeInsert"],
    "FieldDecimalPlaces": ["DecimalsIncrease"],
    "FieldDefaultValue": ["PropertySheet"],
    "FieldDelete": ["Delete"],
    "FieldFormat": ["FormatCellsDialog"],
    "FieldIndexed": ["IndexInsert"],
    "FieldList": ["FieldList"],
    "FieldMoreFields": ["MoreControlsDialog"],
    "FieldNameCaption": ["NameDefine"],
    "FieldNumber": ["Numbering"],
    "FieldRequired": ["Spelling"],
    "FieldShortText": ["TextBoxInsert"],
    "FieldSize": ["SizeToFit"],
    "FieldUnique": ["Lock"],
    "FieldValidation": ["DataValidation"],
    "FieldYesNo": ["FormControlCheckBox", "ControlCheckBox"],
    "FormCreate": ["CreateFormInDesignView"],
    "FormDesign": ["CreateFormInDesignView"],
    "FormWizard": ["AccessFormWizard", "CreateFormFromWizard"],
    "GoToMenu": ["GoTo"],
    "GridlinesMenu": ["GridlinesGallery", "ViewGridlinesWord"],
    "GroupSortTotal": ["RecordsTotals", "TotalsMenu", "AutoSum"],
    "ImportAccess": ["ImportAccess"],
    "ImportExcel": ["ImportExcel"],
    "ImportMore": ["ImportMoreMenu"],
    "ImportNewDataSource": ["DatabaseInsert"],
    "ImportODBC": ["DatabaseInsert"],
    "ImportText": ["ImportTextFile"],
    "ImportXml": ["ImportXmlFile", "XmlImport"],
    "Indexes": ["IndexInsert"],
    "InsertColumnLeft": ["TableColumnsInsertLeft"],
    "InsertColumnRight": ["TableColumnsInsertRight"],
    "InsertRowAbove": ["TableRowsInsertAboveWord"],
    "InsertRowBelow": ["TableRowsInsertBelowWord"],
    "LabelWizard": ["LabelsDialog"],
    "LogoInsert": ["PictureInsertFromFile"],
    "MacroActionCatalog": ["MacroDefault"],
    "MacroCollapseActions": ["OutlineCollapse"],
    "MacroCollapseAll": ["OutlineCollapse", "OutlineCollapseAll"],
    "MacroCreate": ["CreateMacro", "MacroDefault"],
    "MacroExpandActions": ["OutlineExpand"],
    "MacroExpandAll": ["OutlineExpandAll"],
    "MacroRun": ["MacroPlay"],
    "MacroShowAllActions": ["ReviewShowAllComments"],
    "MacroSingleStep": ["MacroSingleStep"],
    "ManageDataCollectionMessages": ["CreateEmail", "MailMergeStartEmail", "FileNewEmail"],
    "MoreFormsGallery": ["CreateFormMoreFormsGallery", "FormCreate"],
    "MoveToAccessDatabase": ["ExportAccess"],
    "MoveToSharePoint": ["FilePublishToSharePoint"],
    "NavigationFormGallery": ["RmsNavigationBar", "AccessNavigationOptions", "CreateFormWithMultipleItems"],
    "PageNumbersInsert": ["HeaderFooterPageNumberInsert"],
    "PasteAppend": ["Paste"],
    "PropertySheet": ["PropertySheet"],
    "PrimaryKey": ["AdpPrimaryKey", "SetDatabasePassword", "Lock"],
    "QueryDeleteRows": ["QueryDelete", "QueryDeleteRows"],
    "QueryDesign": ["CreateQueryInDesignView"],
    "QueryInsertRows": ["QueryAppend", "QueryInsertRows"],
    "QueryReturn": ["QueryReturnGallery"],
    "QueryRun": ["QueryRunQuery", "MacroRun"],
    "QueryTableNames": ["QueryTableNamesShowHide"],
    "QueryTotals": ["QueryTotalsShowHide", "RecordsTotals"],
    "QueryTypeAppend": ["QueryAppend"],
    "QueryTypeCrosstab": ["QueryCrosstab"],
    "QueryTypeDataDefinition": ["QueryDataDefinition"],
    "QueryTypeDelete": ["QueryDelete"],
    "QueryTypeMakeTable": ["QueryMakeTable"],
    "QueryTypePassThrough": ["QuerySqlPassThroughQuery"],
    "QueryTypeSelect": ["QuerySelectQueryType"],
    "QueryTypeUnion": ["QueryUnionQuery"],
    "QueryTypeUpdate": ["QueryUpdate"],
    "QueryWizard": ["CreateQueryFromWizard"],
    "RecordsDeleteRecord": ["RecordsDeleteRecord"],
    "RecordsFirst": ["MailMergeGoToFirstRecord"],
    "RecordsLast": ["MailMergeGotToLastRecord"],
    "RecordsMore": ["RecordsMoreRecordsMenu"],
    "RecordsMoreMenu": ["RecordsMoreRecordsMenu", "GoToMenuAccess"],
    "RecordsNewRecord": ["GoToNewRecord", "DataFormAddRecord"],
    "RecordsNext": ["MailMergeGoToNextRecord"],
    "RecordsPrevious": ["MailMergeGoToPreviousRecord"],
    "RecordsRefresh": ["RecordsRefreshRecords", "Refresh"],
    "RecordsSaveRecord": ["RecordsSaveRecord"],
    "Relationships": ["DatabaseRelationships"],
    "RemoveSort": ["SortRemoveAllSorts", "SortClear"],
    "ReportCreate": ["CreateReportInDesignView"],
    "ReportDesign": ["CreateReportInDesignView"],
    "ReportWizard": ["CreateReportFromWizard"],
    "SavedExports": ["ExportSavedExports", "ExportMoreMenu"],
    "SavedImports": ["ImportMoreMenu"],
    "SendObjectAsEmailAttachment": ["FileEmailAsPdfEmailAttachment", "CreateEmail", "FileNewEmail"],
    "SharePointLists": ["ImportSharePointList", "ExportSharePointList", "SharePointListsWorkOffline"],
    "SizeSpaceMenu": ["SizeToFit"],
    "SortAscending": ["SortAscendingExcel", "SortAscending"],
    "SortDescending": ["SortDescendingExcel", "SortDescending"],
    "TableAfterDeleteMacro": ["MacroDefault", "CreateMacro"],
    "TableAfterInsertMacro": ["MacroDefault", "CreateMacro"],
    "TableAfterUpdateMacro": ["MacroDefault", "CreateMacro"],
    "TableBeforeChangeMacro": ["MacroDefault", "CreateMacro"],
    "TableBeforeDeleteMacro": ["MacroDefault", "CreateMacro"],
    "TableCreate": ["CreateTableInDesignView", "TableInsert"],
    "TableDescription": ["FileDatabaseProperties", "PropertySheet"],
    "TableDesign": ["TableDesign"],
    "TableTemplates": ["TableInsert"],
    "TestValidationRules": ["TableTestValidationRules", "DataValidation"],
    "TitleInsert": ["ControlTitle", "HeaderFooterInsert"],
    "ToggleFilter": ["FilterToggleFilter", "Filter"],
    "Totals": ["Subtotal", "AutoSum"],
    "ViewMultiplePages": ["MultiplePages", "PrintPreviewMultiplePagesMenu"],
    "ViewOnePage": ["ZoomOnePage", "ReadingViewShowOnePage"],
    "ViewMenu": ["ViewsFormView", "ViewNormalViewExcel"],
    "VisualBasic": ["VisualBasicEditor", "VisualBasic"],
    "WordMailMerge": ["MailMergeStart", "MailMergeMergeToDocument"],
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


class OfficeVbaIconExporter:
    def __init__(self, size: int = 128, visible: bool = True):
        self.size = size
        self.visible = visible
        self.excel = None
        self.workbook = None

    def __enter__(self):
        if not VBA_EXPORTER.exists():
            raise FileNotFoundError(f"VBA exporter not found: {VBA_EXPORTER}")

        pythoncom.CoInitialize()
        print("Opening Excel as the Office VBA image host...")
        self.excel = win32com.client.DispatchEx("Excel.Application")
        self.excel.Visible = self.visible
        self.excel.DisplayAlerts = False
        self.workbook = self.excel.Workbooks.Add()
        print("Importing VBA exporter...")
        try:
            component = self.workbook.VBProject.VBComponents.Import(str(VBA_EXPORTER))
            component.Name = "IconExporter"
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


def harvest_ids_via_vba(ids, output_dir: Path, size: int = 128, visible: bool = True):
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    with OfficeVbaIconExporter(size=size, visible=visible) as exporter:
        for index, id_mso in enumerate(ids, start=1):
            print(f"[access vba {index}/{len(ids)}] {id_mso}")
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
                            "Source": f"Local Access VBA GetImageMso:{image_mso}",
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


def write_csv(path: Path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["idMso", "Label", "BitmapPath", "PngPath", "Source"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Access 2021 icon harvester")
    parser.add_argument("--ids", type=str, default="", help="Comma-separated IDs to test")
    parser.add_argument("--size", type=int, default=128, help="Icon size to request from Access")
    parser.add_argument("--layout", type=str, default=str(PROJECT_ROOT / "Practical" / "Layout" / "access2021_ribbon_layout_contextual_full.json"))
    parser.add_argument("--output", type=str, default=str(PROJECT_ROOT / "Practical" / "Images" / "Access"))
    parser.add_argument("--hidden", action="store_true", help="Run Access hidden")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    ids = [p.strip() for p in args.ids.split(",") if p.strip()] if args.ids else extract_ids_from_layout(Path(args.layout))

    print("Starting Access icon harvest...")
    rows = harvest_ids_via_vba(ids, output_dir, size=args.size, visible=not args.hidden)
    write_csv(output_dir / "access_icons.csv", rows)

    print()
    print(f"Saved {len(rows)} valid icons to {output_dir}")
    print("Most important file:")
    print(output_dir / "access_icons.csv")


if __name__ == "__main__":
    main()
