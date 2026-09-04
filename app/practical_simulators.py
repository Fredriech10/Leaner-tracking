import json
import re
from pathlib import Path


WORD_INSERT_PICTURE_SIMULATOR_KEY = "word_insert_picture"
HTML_BASIC_PAGE_SIMULATOR_KEY = "html_basic_page"
EXCEL_DATA_FORMULA_SIMULATOR_KEY = "excel_data_formula"
EXCEL_CHART_CAPTION_SIMULATOR_KEY = "excel_chart_caption"
ACCESS_TABLE_SIMULATOR_KEY = "access_table_design"
ACCESS_QUERY_SIMULATOR_KEY = "access_query_design"
ACCESS_FORM_SIMULATOR_KEY = "access_form_design"
ACCESS_REPORT_SIMULATOR_KEY = "access_report_design"
WORD_CAPS_PRACTICAL_KEY = "word_caps_practical"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORD_RIBBON_LAYOUT_PATH = PROJECT_ROOT / "Practical" / "Layout" / "word2021_ribbon_layout_full.json"
EXCEL_RIBBON_LAYOUT_PATH = PROJECT_ROOT / "Practical" / "Layout" / "excel2021_ribbon_layout_full.json"
ACCESS_RIBBON_LAYOUT_PATH = PROJECT_ROOT / "Practical" / "Layout" / "access2021_ribbon_layout_contextual_full.json"

WORD_TAB_IDS = {
    "TabHome": "home",
    "TabInsert": "insert",
    "TabWordDesign": "design",
    "TabPageLayoutWord": "layout",
    "TabReferences": "references",
    "TabMailings": "mailings",
    "TabReviewWord": "review",
    "TabView": "view",
    "TabDeveloper": "developer",
    "TabHelp": "help",
}

WORD_CONTROL_IDS = {
    "Paste": "home.paste",
    "Cut": "home.cut",
    "Copy": "home.copy",
    "FormatPainter": "home.format_painter",
    "FontSizeIncrease": "home.grow_font",
    "FontSizeDecrease": "home.shrink_font",
    "ChangeCase": "home.change_case",
    "ClearFormatting": "home.clear_formatting",
    "Bold": "home.bold",
    "Italic": "home.italic",
    "Underline": "home.underline",
    "Strikethrough": "home.strikethrough",
    "Subscript": "home.subscript",
    "Superscript": "home.superscript",
    "TextEffectsGallery": "home.text_effects",
    "TextHighlightColorPicker": "home.highlight",
    "FontColorPicker": "home.font_color",
    "Bullets": "home.bullets",
    "Numbering": "home.numbering",
    "MultilevelListGallery": "home.multilevel",
    "IndentDecreaseWord": "home.decrease_indent",
    "IndentIncreaseWord": "home.increase_indent",
    "SortDialog": "home.sort",
    "ShowHide": "home.show_marks",
    "AlignLeft": "home.align_left",
    "AlignCenter": "home.align_center",
    "AlignRight": "home.align_right",
    "AlignJustify": "home.justify",
    "ShadingColorPicker": "home.shading",
    "BordersGallery": "home.borders",
    "FindDialog": "home.find",
    "ReplaceDialog": "home.replace",
    "SelectMenu": "home.select",
    "CoverPageInsertGallery": "insert.cover_page",
    "PageBreakInsertWord": "insert.page_break",
    "TableInsertDialog": "insert.table",
    "PictureInsertFromFile": "insert.pictures",
    "SmartArtInsert": "insert.smartart",
    "ChartInsert": "insert.chart",
    "BookmarkInsert": "insert.bookmark",
    "PageOrientationGallery": "layout.orientation",
    "PageSizeGallery": "layout.size",
    "BreaksGallery": "layout.breaks",
    "FootnoteInsert": "references.insert_footnote",
    "CitationInsert": "references.insert_citation",
    "CitationsManageSources": "references.manage_sources",
    "CaptionInsert": "references.caption",
    "MailMergeStart": "mailings.start_merge",
    "MailMergeInsertMergeField": "mailings.insert_merge_field",
}

WORD_ICON_FALLBACKS = {
    "home.font": "FontSizeIncrease.png",
    "home.styles_gallery": "StylesPane.png",
    "design.style_set": "ThemesGallery.png",
    "design.paragraph_spacing": "LineSpacing.png",
    "layout.indent_left": "IndentDecreaseWord.png",
    "layout.indent_right": "IndentIncreaseWord.png",
    "layout.spacing_before": "LineSpacing.png",
    "layout.spacing_after": "LineSpacing.png",
    "references.next_footnote": "FootnotesShow.png",
    "references.style": "CitationsManageSources.png",
    "mailings.highlight_merge_fields": "TextHighlightColorPicker.png",
    "mailings.first_record": "MailMergePreviewResults.png",
    "mailings.previous_record": "PreviousComment.png",
    "mailings.record_number": "MailMergeFindRecipient.png",
    "mailings.next_record": "NextComment.png",
    "mailings.last_record": "MailMergePreviewResults.png",
    "review.check_accessibility": "SpellingAndGrammar.png",
    "review.show_comments": "NewComment.png",
    "view.read_mode": "ReadAloud.png",
}

EXCEL_TAB_IDS = {
    "TabHome": "home",
    "TabInsert": "insert",
    "TabDrawInk": "draw",
    "TabPageLayoutExcel": "page_layout",
    "TabFormulas": "formulas",
    "TabData": "data",
    "TabReview": "review",
    "TabView": "view",
    "TabDeveloper": "developer",
}

EXCEL_CHART_CONTROL_IDS = {
    "RecommendedCharts",
    "ChartInsertColumn",
    "ChartInsertLine",
    "ChartInsertPie",
    "ChartInsertHierarchy",
    "ChartInsertStatistic",
    "ChartInsertScatter",
    "ChartInsertWaterfall",
    "PivotChartInsert",
}


def _word_caps_question_bank():
    items = [
        ("Font Size", "Format the selected sentence so that it displays at 24 pt.", ["home", "home.font_size"], "Formatting"),
        ("Font Color", "Format the selected text so that the font colour is red.", ["home", "home.font_color"], "Formatting"),
        ("Bullet List", "Turn the selected three lines into a bulleted list.", ["home", "home.bullets"], "Paragraph"),
        ("Numbered List", "Turn the selected three procedure steps into a numbered list.", ["home", "home.numbering"], "Paragraph"),
        ("Insert Chart", "Add a column chart to the document to show the supplied results.", ["insert", "insert.chart"], "Insert"),
        ("Insert Picture", "Insert the campus photo into the document.", ["insert", "insert.pictures"], "Insert"),
        ("Insert Table", "Create a table with exactly 3 columns and 6 rows.", ["insert", "insert.table", "insert.table_apply"], "Insert"),
        ("Insert Sources", "Add a complete book source with an author, title, and year.", ["references", "references.manage_sources"], "References"),
        ("Insert Citation", "Insert the Naidoo 2024 citation at the cursor position.", ["references", "references.insert_citation"], "References"),
        ("Insert Footnote", "Add a footnote containing explanatory text for the selected word.", ["references", "references.insert_footnote"], "References"),
        ("Insert Caption", "Add a Figure caption with caption text for the selected object.", ["references", "references.caption"], "References"),
        ("Insert Bookmark", "Create a bookmark named bmResults at the current location.", ["insert", "insert.bookmark"], "Insert"),
        ("Apply Heading", "Format the selected heading text with the Heading 1 style.", ["home", "home.style_heading1"], "Styles"),
        ("Align Left", "Set the selected paragraph alignment to left.", ["home", "home.align_left"], "Paragraph"),
        ("Align Center", "Set the selected paragraph alignment to centre.", ["home", "home.align_center"], "Paragraph"),
        ("Align Right", "Set the selected paragraph alignment to right.", ["home", "home.align_right"], "Paragraph"),
        ("Justify Text", "Justify the selected paragraph so both edges align evenly.", ["home", "home.justify"], "Paragraph"),
        ("Table Borders", "Apply all borders to the selected table.", ["home", "home.borders"], "Table"),
        ("Paragraph Borders", "Apply an outside border around the selected paragraph.", ["home", "home.borders"], "Paragraph"),
        ("Find", "Search the document for the word TABLES.", ["home", "home.find"], "Editing"),
        ("Replace", "Use Replace to find all the words CAR and replace them with MOTOR.", ["home", "home.replace", "home.replace_apply"], "Editing"),
        ("Shading", "Apply yellow shading to the selected paragraph.", ["home", "home.shading"], "Paragraph"),
        ("Change Orientation", "Change the page orientation to landscape.", ["layout", "layout.orientation"], "Layout"),
        ("Change Page Size", "Change the paper size to Legal.", ["layout", "layout.size"], "Layout"),
        ("Add Page Break", "Insert a page break at the cursor position.", ["insert", "insert.page_break"], "Layout"),
        ("Add Column Break", "Insert a column break at the cursor position.", ["layout", "layout.breaks"], "Layout"),
        ("Add Cover Page", "Add the Annual style cover page to the front of the document.", ["insert", "insert.cover_page"], "Insert"),
        ("Insert SmartArt", "Insert a Basic Process SmartArt graphic.", ["insert", "insert.smartart"], "Insert"),
        ("Edit SmartArt", "Insert a Basic Process SmartArt graphic and change its colour scheme to green.", ["insert", "insert.smartart", "smartart_format"], "Insert"),
        ("Left Indent", "Set the selected paragraph's left indent to 1.27 cm.", ["layout", "layout.indent_left"], "Layout"),
        ("Right Indent", "Set the selected paragraph's right indent to 1.27 cm.", ["layout", "layout.indent_right"], "Layout"),
        ("Mail Merge", "Start a letters mail merge for the document.", ["mailings", "mailings.start_merge"], "Mailings"),
        ("Insert Merge Fields", "Insert the FirstName merge field into the document.", ["mailings", "mailings.insert_merge_field"], "Mailings"),
        ("Font Size", "Format the selected announcement line so that it displays at 24 pt.", ["home", "home.font_size"], "Formatting"),
        ("Font Color", "Change the selected warning text so that its font colour is red.", ["home", "home.font_color"], "Formatting"),
        ("Bullet List", "Convert the selected list of stationery items into bullet points.", ["home", "home.bullets"], "Paragraph"),
        ("Numbered List", "Convert the selected instructions into a numbered sequence.", ["home", "home.numbering"], "Paragraph"),
        ("Apply Heading", "Apply the Heading 1 style to the document title.", ["home", "home.style_heading1"], "Styles"),
        ("Shading", "Highlight the selected notice paragraph with yellow paragraph shading.", ["home", "home.shading"], "Paragraph"),
        ("Insert Table", "Insert a 3 column by 6 row register table.", ["insert", "insert.table", "insert.table_apply"], "Insert"),
        ("Insert Picture", "Place the campus photo in the document body.", ["insert", "insert.pictures"], "Insert"),
        ("Insert Chart", "Insert a column chart for the selected learner totals.", ["insert", "insert.chart"], "Insert"),
        ("Change Orientation", "Set the page layout to landscape orientation.", ["layout", "layout.orientation"], "Layout"),
        ("Change Page Size", "Set the document paper size to Legal.", ["layout", "layout.size"], "Layout"),
        ("Paragraph Borders", "Place an outside border around the selected notice paragraph.", ["home", "home.borders"], "Paragraph"),
        ("Edit SmartArt", "Create a Basic Process SmartArt diagram and apply the green colour option.", ["insert", "insert.smartart", "smartart_format"], "Insert"),
        ("Mail Merge", "Prepare the document as a letters mail merge.", ["mailings", "mailings.start_merge"], "Mailings"),
        ("Insert Merge Fields", "Add the FirstName merge field where the greeting should appear.", ["mailings", "mailings.insert_merge_field"], "Mailings"),
        ("Bold Text", "Make the selected keyword bold.", ["home", "home.bold"], "Formatting"),
        ("Italic Text", "Make the selected book title italic.", ["home", "home.italic"], "Formatting"),
        ("Underline Text", "Underline the selected subheading.", ["home", "home.underline"], "Formatting"),
        ("Highlight Text", "Apply yellow text highlight to the selected phrase.", ["home", "home.highlight"], "Formatting"),
        ("Clear Formatting", "Remove formatting from the selected text so it returns to normal body text.", ["home", "home.clear_formatting"], "Formatting"),
        ("Copy Text", "Copy the selected sentence to the clipboard.", ["home", "home.copy"], "Clipboard"),
        ("Paste Text", "Paste the copied sentence into the blank paragraph.", ["home", "home.paste"], "Clipboard"),
        ("Format Painter", "Copy the formatting from the sample heading and apply it to the selected heading.", ["home", "home.format_painter"], "Clipboard"),
        ("Grow Font", "Increase the size of the selected heading by one font-size step.", ["home", "home.grow_font"], "Formatting"),
        ("Shrink Font", "Decrease the size of the selected heading by one font-size step.", ["home", "home.shrink_font"], "Formatting"),
        ("Strikethrough Text", "Apply strikethrough formatting to the selected completed item.", ["home", "home.strikethrough"], "Formatting"),
        ("Superscript Text", "Format the selected number as superscript.", ["home", "home.superscript"], "Formatting"),
        ("Subscript Text", "Format the selected number as subscript.", ["home", "home.subscript"], "Formatting"),
        ("Add Table Row", "Insert one new row below the selected table row.", ["table_layout", "table_layout.insert_row_below"], "Table"),
        ("Add Table Column", "Insert one new column to the right of the selected table column.", ["table_layout", "table_layout.insert_column_right"], "Table"),
        ("Delete Table Row", "Delete the selected row from the table.", ["table_layout", "table_layout.delete_row"], "Table"),
        ("Merge Table Cells", "Merge the two selected cells in the first row of the table.", ["table_layout", "table_layout.merge_cells"], "Table"),
    ]
    target_defaults = {
        "Font Size": {"type": "text", "label": "selected sentence"},
        "Font Color": {"type": "text", "label": "selected text"},
        "Bold Text": {"type": "text", "label": "selected keyword"},
        "Italic Text": {"type": "text", "label": "selected book title"},
        "Underline Text": {"type": "text", "label": "selected subheading"},
        "Highlight Text": {"type": "text", "label": "selected phrase"},
        "Clear Formatting": {"type": "text", "label": "selected formatted text"},
        "Copy Text": {"type": "text", "label": "selected sentence"},
        "Paste Text": {"type": "paragraph", "label": "blank paragraph"},
        "Format Painter": {"type": "text", "label": "selected heading"},
        "Grow Font": {"type": "text", "label": "selected heading"},
        "Shrink Font": {"type": "text", "label": "selected heading"},
        "Strikethrough Text": {"type": "text", "label": "selected completed item"},
        "Superscript Text": {"type": "text", "label": "selected number"},
        "Subscript Text": {"type": "text", "label": "selected number"},
        "Add Table Row": {"type": "object", "label": "selected table row"},
        "Add Table Column": {"type": "object", "label": "selected table column"},
        "Delete Table Row": {"type": "object", "label": "selected table row"},
        "Merge Table Cells": {"type": "object", "label": "two selected cells in the first row"},
        "Bullet List": {"type": "text", "label": "selected three lines"},
        "Numbered List": {"type": "text", "label": "selected procedure steps"},
        "Insert Chart": {"type": "paragraph", "label": "below the Results Summary paragraph"},
        "Insert Picture": {"type": "paragraph", "label": "below the School Campus paragraph"},
        "Insert Table": {"type": "paragraph", "label": "below the Learner Register heading"},
        "Insert Sources": {"type": "document", "label": "references for the report"},
        "Insert Citation": {"type": "cursor", "label": "end of the research sentence"},
        "Insert Footnote": {"type": "text", "label": "selected word"},
        "Insert Caption": {"type": "object", "label": "selected object"},
        "Insert Bookmark": {"type": "cursor", "label": "Results section heading"},
        "Apply Heading": {"type": "text", "label": "document title"},
        "Align Left": {"type": "paragraph", "label": "selected paragraph"},
        "Align Center": {"type": "paragraph", "label": "selected paragraph"},
        "Align Right": {"type": "paragraph", "label": "selected paragraph"},
        "Justify Text": {"type": "paragraph", "label": "selected paragraph"},
        "Table Borders": {"type": "object", "label": "selected table"},
        "Paragraph Borders": {"type": "paragraph", "label": "selected notice paragraph"},
        "Find": {"type": "document", "label": "whole document"},
        "Replace": {"type": "document", "label": "whole document"},
        "Shading": {"type": "paragraph", "label": "selected notice paragraph"},
        "Change Orientation": {"type": "document", "label": "whole document"},
        "Change Page Size": {"type": "document", "label": "whole document"},
        "Add Page Break": {"type": "cursor", "label": "cursor position after Page 1 content"},
        "Add Column Break": {"type": "cursor", "label": "cursor position in Column 1"},
        "Add Cover Page": {"type": "document", "label": "front of the document"},
        "Insert SmartArt": {"type": "paragraph", "label": "below the Process heading"},
        "Edit SmartArt": {"type": "object", "label": "selected SmartArt graphic"},
        "Left Indent": {"type": "paragraph", "label": "selected paragraph"},
        "Right Indent": {"type": "paragraph", "label": "selected paragraph"},
        "Mail Merge": {"type": "document", "label": "mail merge letter"},
        "Insert Merge Fields": {"type": "cursor", "label": "greeting line"},
    }

    def build_metadata(title, steps):
        actionable_steps = [step for step in steps if step not in {"home", "insert", "layout", "references", "mailings", "smartart_format", "table_layout"}]
        first_tab = next((step for step in steps if step in {"insert", "layout", "references", "mailings", "smartart_format", "table_layout"}), "home")
        tab_clicks = 0 if first_tab == "home" else 1
        target = target_defaults.get(title, {"type": "selection", "label": "correct item"})
        return {
            "start_tab": "home",
            "ideal_clicks": 1 + tab_clicks + len(actionable_steps),
            "target_clicks": 1,
            "free_misclicks": 1,
            "penalty_per_misclick": 0.5,
            "max_misclick_penalty": 2,
            "requires_target_selection": True,
            "target": target,
            "accepted_controls": [step for step in steps if step not in {"home", "insert", "layout", "references", "mailings"}],
        }

    bank = []
    for idx, (title, prompt, steps, category) in enumerate(items, start=1):
        metadata = build_metadata(title, steps)
        bank.append(
            {
                "seed_key": f"word_caps_{idx:03d}",
                "program": "word",
                "category": category,
                "title": title,
                "prompt_html": f"<p>{prompt}</p>",
                "steps": steps,
                "marks": len(steps),
                "caps_tags": "word,caps",
                "metadata": metadata,
            }
        )
    return bank


WORD_CAPS_QUESTION_BANK = _word_caps_question_bank()


def get_word_caps_question_bank():
    return [dict(item) for item in WORD_CAPS_QUESTION_BANK]


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_") or "item"


def _tooltip_key(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _layout_tabs(data):
    tabs = list(data.get("tabs", []))
    tabs.extend(data.get("baseTabs", []))
    for ribbon_set in data.get("contextualRibbonSets", []):
        tabs.extend(ribbon_set.get("tabs", []))
    return tabs


def _load_ribbon_tooltip_map(layout_path):
    if not layout_path.exists():
        return {}
    try:
        data = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    tooltips = {}
    for tab in _layout_tabs(data):
        for group in tab.get("groups", []):
            for control in group.get("controls", []):
                tooltip = control.get("tooltip")
                if not tooltip:
                    continue
                for value in (control.get("label"), control.get("idMso")):
                    key = _tooltip_key(value)
                    if key:
                        tooltips.setdefault(key, tooltip)
    return tooltips


def _fallback_control_id(tab_id, control):
    id_mso = control.get("idMso")
    if id_mso:
        return WORD_CONTROL_IDS.get(id_mso, f"{tab_id}.{_slug(id_mso)}")
    return f"{tab_id}.{_slug(control.get('label'))}"


def _word_icon_url(image_name):
    if not image_name:
        return None
    return f"/practical_assets/Word/{image_name}?v=word-ribbon-2"


def _excel_icon_url(image_name):
    if not image_name:
        return None
    return f"/practical_assets/Excel/{image_name}?v=office-ribbon-2"


def _build_excel_ribbon_from_layout():
    if not EXCEL_RIBBON_LAYOUT_PATH.exists():
        return None
    try:
        layout = json.loads(EXCEL_RIBBON_LAYOUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    tabs = []
    for tab in layout.get("tabs", []):
        tab_id = EXCEL_TAB_IDS.get(tab.get("idMso"), _slug(tab.get("label")))
        groups = []
        for group in tab.get("groups", []):
            controls = []
            for control in group.get("controls", []):
                id_mso = control.get("idMso")
                label = control.get("label") or id_mso or "Control"
                controls.append({
                    "id": f"{tab_id}.{_slug(id_mso or label)}",
                    "id_mso": id_mso,
                    "label": label,
                    "tooltip": control.get("tooltip") or label,
                    "image_url": _excel_icon_url(control.get("image")),
                    "kind": "menu" if control.get("type") in {"menu", "gallery", "splitButton", "comboBox", "numericField"} else "button",
                    "size": control.get("size") or "small",
                    "is_chart_insert": id_mso in EXCEL_CHART_CONTROL_IDS,
                })
            groups.append({
                "title": group.get("label") or "Group",
                "class_name": f"group-{_slug(group.get('label'))}",
                "controls": controls,
            })
        tabs.append({
            "id": tab_id,
            "id_mso": tab.get("idMso"),
            "label": tab.get("label") or tab_id.title(),
            "groups": groups,
        })

    icon_urls = sorted({
        control["image_url"]
        for tab in tabs
        for group in tab["groups"]
        for control in group["controls"]
        if control.get("image_url")
    })
    return {"tabs": tabs, "icon_urls": icon_urls, "default_tab": "home"}


def _build_word_shell_from_layout(task_title, active_tabs, active_controls, shell_mode, inactive_controls_style):
    if not WORD_RIBBON_LAYOUT_PATH.exists():
        return None
    try:
        layout = json.loads(WORD_RIBBON_LAYOUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    tabs = []
    for tab in layout.get("tabs", []):
        tab_id = WORD_TAB_IDS.get(tab.get("idMso"), _slug(tab.get("label")))
        groups = []
        for group in tab.get("groups", []):
            group_slug = _slug(group.get("label"))
            controls = []
            if tab_id == "home" and group_slug == "font":
                controls.extend([
                    {"id": "home.font_family", "label": "Calibri", "icon": "Aa", "kind": "menu", "size": "field"},
                    {"id": "home.font_size", "label": "11", "icon": "11", "kind": "menu", "size": "field"},
                ])
            for control in group.get("controls", []):
                control_id = _fallback_control_id(tab_id, control)
                if control_id in {"home.font_family", "home.font_size"}:
                    continue
                controls.append({
                    "id": control_id,
                    "id_mso": control.get("idMso"),
                    "label": control.get("label") or control.get("idMso") or "Control",
                    "tooltip": control.get("tooltip") or control.get("label") or control.get("idMso") or "Control",
                    "icon": (control.get("label") or control.get("idMso") or "?")[:2],
                    "image_url": _word_icon_url(control.get("image") or WORD_ICON_FALLBACKS.get(control_id)),
                    "kind": "menu" if control.get("type") in {"menu", "gallery", "splitButton", "comboBox", "numericField"} else "button",
                    "size": control.get("size") or "small",
                    "row": control.get("row"),
                    "column": control.get("column"),
                    "row_span": control.get("rowSpan"),
                    "col_span": control.get("colSpan"),
                })
            if tab_id == "home" and group_slug == "styles" and not any(c["id"] == "home.style_heading1" for c in controls):
                controls.append({
                    "id": "home.style_heading1",
                    "id_mso": None,
                    "label": "Heading 1",
                    "tooltip": "Heading 1 - Home > Styles",
                    "icon": "Aa",
                    "image_url": _word_icon_url("StylesPane.png"),
                    "kind": "button",
                    "size": "large",
                    "row": 1,
                    "column": 3,
                    "row_span": 3,
                    "col_span": 1,
                })
            groups.append({
                "title": group.get("label") or "Group",
                "class_name": f"group-{group_slug}",
                "controls": controls,
            })
        tabs.append({
            "id": tab_id,
            "id_mso": tab.get("idMso"),
            "label": tab.get("label") or tab_id.title(),
            "groups": groups,
        })

    if "smartart_format" in active_tabs:
        tabs.append({
            "id": "smartart_format",
            "label": "SmartArt Design",
            "groups": [{
                "title": "SmartArt Styles",
                "class_name": "group-smartart-styles",
                "controls": [
                    {"id": "smartart_format", "label": "Change Colors", "tooltip": "Change Colors - SmartArt Design > SmartArt Styles", "icon": "Aa", "kind": "menu", "image_url": _word_icon_url("SmartArtInsert.png")},
                ],
            }],
        })

    if "table_layout" in active_tabs:
        tabs.append({
            "id": "table_layout",
            "label": "Table Layout",
            "groups": [
                {
                    "title": "Rows & Columns",
                    "class_name": "group-table-layout-rows",
                    "controls": [
                        {"id": "table_layout.insert_row_below", "label": "Insert Below", "tooltip": "Insert Below - Table Layout > Rows & Columns", "icon": "⊞", "kind": "button", "image_url": "/practical_assets/Access/InsertRowBelow.png?v=office-ribbon-2"},
                        {"id": "table_layout.insert_column_right", "label": "Insert Right", "tooltip": "Insert Right - Table Layout > Rows & Columns", "icon": "⊟", "kind": "button", "image_url": "/practical_assets/Access/InsertColumnRight.png?v=office-ribbon-2"},
                        {"id": "table_layout.delete_row", "label": "Delete Row", "tooltip": "Delete Rows - Table Layout > Rows & Columns", "icon": "⌫", "kind": "button", "image_url": "/practical_assets/Access/QueryDeleteRows.png?v=office-ribbon-2"},
                    ],
                },
                {
                    "title": "Merge",
                    "class_name": "group-table-layout-merge",
                    "controls": [
                        {"id": "table_layout.merge_cells", "label": "Merge Cells", "tooltip": "Merge Cells - Table Layout > Merge", "icon": "⊡", "kind": "button", "image_url": "/practical_assets/Excel/MergeAndCenter.png?v=office-ribbon-2"},
                    ],
                },
            ],
        })

    icon_urls = sorted({
        control["image_url"]
        for tab in tabs
        for group in tab["groups"]
        for control in group["controls"]
        if control.get("image_url")
    })

    return {
        "app": "word",
        "mode": shell_mode,
        "inactive_controls_style": inactive_controls_style,
        "title": task_title,
        "tabs": tabs,
        "active_tabs": active_tabs,
        "active_controls": active_controls,
        "default_tab": "home",
        "default_context_tab": "smartart_format" if "smartart_format" in active_tabs else None,
        "layout_source": "word2021_ribbon_layout_full.json",
        "asset_source": "Practical/Images/Word",
        "icon_urls": icon_urls,
        "menus": {
            "insert.pictures": {
                "title": "Insert Picture",
                "description": "Choose an image to insert into the document."
            },
            "insert.table": {
                "title": "Table",
                "description": "Insert tables into your document. This control is visible for realism in this task."
            },
            "layout.wrap_text": {
                "title": "Wrap Text",
                "description": "Wrap text around objects. Use the Picture Format tab for this task."
            },
        },
    }


def build_word_shell(task_title, active_tabs, active_controls, shell_mode="test", inactive_controls_style=None):
    if inactive_controls_style is None:
        inactive_controls_style = "enabled" if shell_mode == "test" else "disabled"
    layout_shell = _build_word_shell_from_layout(task_title, active_tabs, active_controls, shell_mode, inactive_controls_style)
    if layout_shell is not None:
        return layout_shell
    tabs = [
        {"id": "home", "label": "Home", "groups": [
            {"title": "Clipboard", "class_name": "group-clipboard", "controls": [
                {"id": "home.paste", "label": "Paste", "icon": "📋", "kind": "button"},
                {"id": "home.cut", "label": "Cut", "icon": "✂", "kind": "button"},
                {"id": "home.copy", "label": "Copy", "icon": "⧉", "kind": "button"},
                {"id": "home.format_painter", "label": "Painter", "icon": "🖌", "kind": "button"},
            ]},
            {"title": "Font", "class_name": "group-font", "controls": [
                {"id": "home.font_family", "label": "Calibri", "icon": "Aa", "kind": "menu"},
                {"id": "home.font_size", "label": "11", "icon": "11", "kind": "menu"},
                {"id": "home.grow_font", "label": "Grow", "icon": "A▲", "kind": "button"},
                {"id": "home.shrink_font", "label": "Shrink", "icon": "A▼", "kind": "button"},
                {"id": "home.change_case", "label": "Aa", "icon": "Aa", "kind": "menu"},
                {"id": "home.clear_formatting", "label": "Clear", "icon": "⌫", "kind": "button"},
                {"id": "home.bold", "label": "Bold", "icon": "B", "kind": "button"},
                {"id": "home.italic", "label": "Italic", "icon": "I", "kind": "button"},
                {"id": "home.underline", "label": "Underline", "icon": "U", "kind": "button"},
                {"id": "home.strikethrough", "label": "ab", "icon": "ab", "kind": "button"},
                {"id": "home.subscript", "label": "x₂", "icon": "x₂", "kind": "button"},
                {"id": "home.superscript", "label": "x²", "icon": "x²", "kind": "button"},
                {"id": "home.text_effects", "label": "Effects", "icon": "A✦", "kind": "menu"},
                {"id": "home.highlight", "label": "Highlight", "icon": "🖍", "kind": "menu"},
                {"id": "home.font_color", "label": "Color", "icon": "A▁", "kind": "menu"},
            ]},
            {"title": "Paragraph", "class_name": "group-paragraph", "controls": [
                {"id": "home.bullets", "label": "Bullets", "icon": "•", "kind": "button"},
                {"id": "home.numbering", "label": "Number", "icon": "1.", "kind": "button"},
                {"id": "home.multilevel", "label": "List", "icon": "≡", "kind": "menu"},
                {"id": "home.decrease_indent", "label": "Dec", "icon": "⇤", "kind": "button"},
                {"id": "home.increase_indent", "label": "Inc", "icon": "⇥", "kind": "button"},
                {"id": "home.sort", "label": "Sort", "icon": "A↓", "kind": "button"},
                {"id": "home.show_marks", "label": "¶", "icon": "¶", "kind": "button"},
                {"id": "home.align_left", "label": "Left", "icon": "☰", "kind": "button"},
                {"id": "home.align_center", "label": "Center", "icon": "≡", "kind": "button"},
                {"id": "home.align_right", "label": "Right", "icon": "☷", "kind": "button"},
                {"id": "home.justify", "label": "Justify", "icon": "☵", "kind": "button"},
                {"id": "home.shading", "label": "Shade", "icon": "▦", "kind": "menu"},
                {"id": "home.borders", "label": "Border", "icon": "⊞", "kind": "menu"},
            ]},
            {"title": "Styles", "class_name": "group-styles", "controls": [
                {"id": "home.style_normal", "label": "Normal", "icon": "Aa", "kind": "button"},
                {"id": "home.style_no_spacing", "label": "No Sp.", "icon": "Aa", "kind": "button"},
                {"id": "home.style_heading1", "label": "Heading 1", "icon": "AaB", "kind": "button"},
                {"id": "home.style_heading2", "label": "Heading 2", "icon": "AaC", "kind": "button"},
                {"id": "home.style_title", "label": "Title", "icon": "AaB", "kind": "button"},
                {"id": "home.style_subtitle", "label": "Subtitle", "icon": "Aa", "kind": "button"},
            ]},
            {"title": "Editing", "class_name": "group-editing", "controls": [
                {"id": "home.find", "label": "Find", "icon": "⌕", "kind": "menu"},
                {"id": "home.replace", "label": "Replace", "icon": "↺", "kind": "menu"},
                {"id": "home.select", "label": "Select", "icon": "🖱", "kind": "menu"},
            ]},
            {"title": "Adobe Acrobat", "class_name": "group-acrobat", "controls": [
                {"id": "home.create_pdf", "label": "Create PDF", "icon": "PDF", "kind": "button"},
            ]},
        ]},
        {"id": "insert", "label": "Insert", "groups": [
            {"title": "Pages", "class_name": "group-pages", "controls": [
                {"id": "insert.cover_page", "label": "Cover Page", "icon": "▤", "kind": "button"},
                {"id": "insert.blank_page", "label": "Blank Page", "icon": "□", "kind": "button"},
                {"id": "insert.page_break", "label": "Page Break", "icon": "↵", "kind": "button"},
            ]},
            {"title": "Tables", "class_name": "group-table-mini", "controls": [
                {"id": "insert.table", "label": "Table", "icon": "▦", "kind": "menu"},
            ]},
            {"title": "Illustrations", "class_name": "group-illustrations", "controls": [
                {"id": "insert.pictures", "label": "Pictures", "icon": "🖼️", "kind": "menu", "action": "open_insert_dialog"},
                {"id": "insert.shapes", "label": "Shapes", "icon": "⬛", "kind": "menu"},
                {"id": "insert.icons", "label": "Icons", "icon": "⭐", "kind": "menu"},
                {"id": "insert.smartart", "label": "SmartArt", "icon": "🟦", "kind": "menu"},
                {"id": "insert.chart", "label": "Chart", "icon": "📊", "kind": "menu"},
                {"id": "insert.models3d", "label": "3D Models", "icon": "⬡", "kind": "menu"},
                {"id": "insert.screenshot", "label": "Screenshot", "icon": "▣", "kind": "menu"},
            ]},
            {"title": "Add-ins", "class_name": "group-addins", "controls": [
                {"id": "insert.get_addins", "label": "Get Add-ins", "icon": "⊞", "kind": "menu"},
                {"id": "insert.my_addins", "label": "My Add-ins", "icon": "⬠", "kind": "menu"},
                {"id": "insert.wikipedia", "label": "Wikipedia", "icon": "W", "kind": "button"},
            ]},
            {"title": "Media", "class_name": "group-media", "controls": [
                {"id": "insert.online_video", "label": "Online Videos", "icon": "🎞", "kind": "menu"},
            ]},
            {"title": "Links", "class_name": "group-links", "controls": [
                {"id": "insert.link", "label": "Link", "icon": "🔗", "kind": "menu"},
                {"id": "insert.bookmark", "label": "Bookmark", "icon": "🔖", "kind": "menu"},
                {"id": "insert.cross_reference", "label": "Cross-ref", "icon": "↗", "kind": "menu"},
            ]},
            {"title": "Comments", "class_name": "group-comments", "controls": [
                {"id": "insert.comment", "label": "Comment", "icon": "💬", "kind": "button"},
            ]},
            {"title": "Header & Footer", "class_name": "group-header-footer", "controls": [
                {"id": "insert.header", "label": "Header", "icon": "▁", "kind": "menu"},
                {"id": "insert.footer", "label": "Footer", "icon": "▔", "kind": "menu"},
                {"id": "insert.page_number", "label": "Page Number", "icon": "#", "kind": "menu"},
            ]},
            {"title": "Text", "class_name": "group-text", "controls": [
                {"id": "insert.text_box", "label": "Text Box", "icon": "T", "kind": "menu"},
                {"id": "insert.wordart", "label": "WordArt", "icon": "A", "kind": "menu"},
                {"id": "insert.signature", "label": "Signature", "icon": "✎", "kind": "menu"},
                {"id": "insert.date_time", "label": "Date & Time", "icon": "🕘", "kind": "menu"},
                {"id": "insert.object", "label": "Object", "icon": "◫", "kind": "menu"},
            ]},
            {"title": "Symbols", "class_name": "group-symbols", "controls": [
                {"id": "insert.equation", "label": "Equation", "icon": "∏", "kind": "menu"},
                {"id": "insert.symbol", "label": "Symbol", "icon": "Ω", "kind": "menu"},
            ]},
        ]},
        {"id": "design", "label": "Design", "groups": [
            {"title": "Document Formatting", "class_name": "group-document-formatting", "controls": [
                {"id": "design.themes", "label": "Themes", "icon": "◧", "kind": "menu"},
                {"id": "design.colors", "label": "Colors", "icon": "▥", "kind": "menu"},
                {"id": "design.fonts", "label": "Fonts", "icon": "A", "kind": "menu"},
                {"id": "design.paragraph_spacing", "label": "Paragraph Spacing", "icon": "↕", "kind": "menu"},
                {"id": "design.effects", "label": "Effects", "icon": "✎", "kind": "menu"},
                {"id": "design.set_default", "label": "Set as Default", "icon": "✓", "kind": "button"},
            ]},
            {"title": "Page Background", "class_name": "group-page-background", "controls": [
                {"id": "design.watermark", "label": "Watermark", "icon": "◭", "kind": "menu"},
                {"id": "design.page_color", "label": "Page Color", "icon": "◫", "kind": "menu"},
                {"id": "design.page_borders", "label": "Page Borders", "icon": "▣", "kind": "menu"},
            ]},
        ]},
        {"id": "layout", "label": "Layout", "groups": [
            {"title": "Page Setup", "class_name": "group-page-setup", "controls": [
                {"id": "layout.margins", "label": "Margins", "icon": "↔", "kind": "menu"},
                {"id": "layout.orientation", "label": "Orientation", "icon": "↻", "kind": "menu"},
                {"id": "layout.size", "label": "Page Size", "icon": "▭", "kind": "menu"},
                {"id": "layout.columns", "label": "Columns", "icon": "▥", "kind": "menu"},
                {"id": "layout.breaks", "label": "Breaks", "icon": "↵", "kind": "menu"},
                {"id": "layout.line_numbers", "label": "Line Numbers", "icon": "1‒", "kind": "menu"},
                {"id": "layout.hyphenation", "label": "Hyphenation", "icon": "ab", "kind": "menu"},
            ]},
            {"title": "Paragraph", "class_name": "group-layout-paragraph", "controls": [
                {"id": "layout.indent_left", "label": "Left 0 cm", "icon": "⇤", "kind": "menu"},
                {"id": "layout.indent_right", "label": "Right 0 cm", "icon": "⇥", "kind": "menu"},
                {"id": "layout.spacing_before", "label": "Before 0 pt", "icon": "↥", "kind": "menu"},
                {"id": "layout.spacing_after", "label": "After 0 pt", "icon": "↧", "kind": "menu"},
            ]},
            {"title": "Arrange", "class_name": "group-arrange", "controls": [
                {"id": "layout.position", "label": "Position", "icon": "⌖", "kind": "menu"},
                {"id": "layout.wrap_text", "label": "Wrap Text", "icon": "▣", "kind": "menu"},
                {"id": "layout.bring_forward", "label": "Bring", "icon": "▣", "kind": "menu"},
                {"id": "layout.send_backward", "label": "Send", "icon": "◫", "kind": "menu"},
                {"id": "layout.selection_pane", "label": "Selection", "icon": "☰", "kind": "button"},
                {"id": "layout.align", "label": "Align", "icon": "⇔", "kind": "menu"},
                {"id": "layout.group", "label": "Group", "icon": "⊟", "kind": "menu"},
                {"id": "layout.rotate", "label": "Rotate", "icon": "↻", "kind": "menu"},
            ]},
        ]},
        {"id": "references", "label": "References", "groups": [
            {"title": "Table of Contents", "class_name": "group-toc", "controls": [
                {"id": "references.toc", "label": "Contents", "icon": "≣", "kind": "menu"},
                {"id": "references.update_table", "label": "Update", "icon": "↻", "kind": "button"},
                {"id": "references.add_text", "label": "Add Text", "icon": "+", "kind": "menu"},
            ]},
            {"title": "Footnotes", "class_name": "group-footnotes", "controls": [
                {"id": "references.insert_footnote", "label": "Footnote", "icon": "ab¹", "kind": "button"},
                {"id": "references.insert_endnote", "label": "Endnote", "icon": "ab²", "kind": "button"},
                {"id": "references.next_footnote", "label": "Next", "icon": "⇩", "kind": "menu"},
                {"id": "references.show_notes", "label": "Notes", "icon": "☷", "kind": "button"},
            ]},
            {"title": "Research", "class_name": "group-research", "controls": [
                {"id": "references.search", "label": "Search", "icon": "⌕", "kind": "button"},
            ]},
            {"title": "Citations & Bibliography", "class_name": "group-citations", "controls": [
                {"id": "references.insert_citation", "label": "Citation", "icon": "🗎", "kind": "menu"},
                {"id": "references.manage_sources", "label": "Sources", "icon": "🗂", "kind": "button"},
                {"id": "references.style_apa", "label": "APA", "icon": "APA", "kind": "menu"},
                {"id": "references.bibliography", "label": "Bibliography", "icon": "📚", "kind": "menu"},
            ]},
            {"title": "Captions", "class_name": "group-captions", "controls": [
                {"id": "references.caption", "label": "Caption", "icon": "▤", "kind": "menu"},
                {"id": "references.cross_reference", "label": "Cross-ref", "icon": "↗", "kind": "menu"},
                {"id": "references.insert_table_figures", "label": "Figures", "icon": "🖼", "kind": "menu"},
            ]},
            {"title": "Index", "class_name": "group-index", "controls": [
                {"id": "references.mark_entry", "label": "Mark Entry", "icon": "▭", "kind": "menu"},
                {"id": "references.insert_index", "label": "Insert Index", "icon": "📄", "kind": "menu"},
            ]},
            {"title": "Table of Authorities", "class_name": "group-authorities", "controls": [
                {"id": "references.mark_citation", "label": "Mark Citation", "icon": "▭", "kind": "menu"},
                {"id": "references.insert_authorities", "label": "Authorities", "icon": "🧾", "kind": "menu"},
            ]},
        ]},
        {"id": "mailings", "label": "Mailings", "groups": [
            {"title": "Create", "class_name": "group-mail-create", "controls": [
                {"id": "mailings.envelopes", "label": "Envelopes", "icon": "✉", "kind": "button"},
                {"id": "mailings.labels", "label": "Labels", "icon": "🏷", "kind": "button"},
            ]},
            {"title": "Start Mail Merge", "class_name": "group-mail-start", "controls": [
                {"id": "mailings.start_merge", "label": "Start Merge", "icon": "📨", "kind": "menu"},
                {"id": "mailings.select_recipients", "label": "Recipients", "icon": "👥", "kind": "menu"},
                {"id": "mailings.edit_list", "label": "Edit List", "icon": "📝", "kind": "button"},
            ]},
            {"title": "Write & Insert Fields", "class_name": "group-mail-fields", "controls": [
                {"id": "mailings.highlight_fields", "label": "Highlight", "icon": "🖍", "kind": "button"},
                {"id": "mailings.address_block", "label": "Address", "icon": "📄", "kind": "button"},
                {"id": "mailings.greeting_line", "label": "Greeting", "icon": "🗎", "kind": "button"},
                {"id": "mailings.insert_merge_field", "label": "Merge Field", "icon": "⊞", "kind": "menu"},
                {"id": "mailings.rules", "label": "Rules", "icon": "⚑", "kind": "menu"},
                {"id": "mailings.match_fields", "label": "Match Fields", "icon": "≈", "kind": "button"},
                {"id": "mailings.update_labels", "label": "Update Labels", "icon": "↻", "kind": "button"},
            ]},
            {"title": "Preview Results", "class_name": "group-mail-preview", "controls": [
                {"id": "mailings.preview_results", "label": "Preview", "icon": "ABC", "kind": "button"},
                {"id": "mailings.find_recipient", "label": "Find", "icon": "⌕", "kind": "button"},
                {"id": "mailings.check_errors", "label": "Errors", "icon": "✓", "kind": "button"},
            ]},
            {"title": "Finish", "class_name": "group-mail-finish", "controls": [
                {"id": "mailings.finish_merge", "label": "Finish", "icon": "⇢", "kind": "menu"},
            ]},
        ]},
        {"id": "review", "label": "Review", "groups": [
            {"title": "Proofing", "class_name": "group-review-proofing", "controls": [
                {"id": "review.spelling", "label": "Spelling", "icon": "abc", "kind": "button"},
                {"id": "review.word_count", "label": "Word Count", "icon": "123", "kind": "button"},
            ]},
            {"title": "Speech", "class_name": "group-review-speech", "controls": [
                {"id": "review.read_aloud", "label": "Read Aloud", "icon": ")))", "kind": "button"},
            ]},
            {"title": "Accessibility", "class_name": "group-review-accessibility", "controls": [
                {"id": "review.check_accessibility", "label": "Accessibility", "icon": "↻", "kind": "button"},
            ]},
            {"title": "Language", "class_name": "group-review-language", "controls": [
                {"id": "review.translate", "label": "Translate", "icon": "あA", "kind": "menu"},
                {"id": "review.language", "label": "Language", "icon": "文", "kind": "menu"},
            ]},
            {"title": "Comments", "class_name": "group-review-comments", "controls": [
                {"id": "review.new_comment", "label": "Comment", "icon": "💬", "kind": "button"},
                {"id": "review.delete_comment", "label": "Delete", "icon": "✕", "kind": "button"},
                {"id": "review.prev_comment", "label": "Previous", "icon": "↑", "kind": "button"},
                {"id": "review.next_comment", "label": "Next", "icon": "↓", "kind": "button"},
                {"id": "review.show_comments", "label": "Comments", "icon": "☰", "kind": "button"},
            ]},
            {"title": "Tracking", "class_name": "group-review-tracking", "controls": [
                {"id": "review.track_changes", "label": "Track", "icon": "✎", "kind": "menu"},
                {"id": "review.simple_markup", "label": "Markup", "icon": "▾", "kind": "menu"},
                {"id": "review.show_markup", "label": "Show", "icon": "☷", "kind": "menu"},
                {"id": "review.reviewing_pane", "label": "Pane", "icon": "▥", "kind": "button"},
            ]},
            {"title": "Changes", "class_name": "group-review-changes", "controls": [
                {"id": "review.accept", "label": "Accept", "icon": "✓", "kind": "menu"},
                {"id": "review.reject", "label": "Reject", "icon": "✕", "kind": "menu"},
                {"id": "review.previous_change", "label": "Previous", "icon": "←", "kind": "button"},
                {"id": "review.next_change", "label": "Next", "icon": "→", "kind": "button"},
            ]},
            {"title": "Compare", "class_name": "group-review-compare", "controls": [
                {"id": "review.compare", "label": "Compare", "icon": "▤", "kind": "menu"},
            ]},
            {"title": "Protect", "class_name": "group-review-protect", "controls": [
                {"id": "review.block_authors", "label": "Block Authors", "icon": "👤", "kind": "button"},
                {"id": "review.restrict_editing", "label": "Restrict", "icon": "🔒", "kind": "button"},
            ]},
            {"title": "Ink", "class_name": "group-review-ink", "controls": [
                {"id": "review.hide_ink", "label": "Hide Ink", "icon": "〰", "kind": "button"},
            ]},
        ]},
        {"id": "view", "label": "View", "groups": [
            {"title": "Views", "class_name": "group-view-views", "controls": [
                {"id": "view.read_mode", "label": "Read", "icon": "📖", "kind": "button"},
                {"id": "view.print_layout", "label": "Print", "icon": "🗎", "kind": "button"},
                {"id": "view.web_layout", "label": "Web", "icon": "🌐", "kind": "button"},
                {"id": "view.outline", "label": "Outline", "icon": "☰", "kind": "button"},
                {"id": "view.draft", "label": "Draft", "icon": "▤", "kind": "button"},
            ]},
            {"title": "Immersive", "class_name": "group-view-immersive", "controls": [
                {"id": "view.focus", "label": "Focus", "icon": "◐", "kind": "button"},
                {"id": "view.immersive_reader", "label": "Reader", "icon": "📘", "kind": "button"},
            ]},
            {"title": "Page Movement", "class_name": "group-view-page-movement", "controls": [
                {"id": "view.vertical", "label": "Vertical", "icon": "▥", "kind": "button"},
                {"id": "view.side_to_side", "label": "Side", "icon": "▤", "kind": "button"},
            ]},
            {"title": "Show", "class_name": "group-view-show", "controls": [
                {"id": "view.ruler", "label": "Ruler", "icon": "☑", "kind": "button"},
                {"id": "view.gridlines", "label": "Grid", "icon": "☐", "kind": "button"},
                {"id": "view.navigation", "label": "Nav", "icon": "☐", "kind": "button"},
            ]},
            {"title": "Zoom", "class_name": "group-view-zoom", "controls": [
                {"id": "view.zoom", "label": "Zoom", "icon": "⌕", "kind": "button"},
                {"id": "view.zoom_100", "label": "100%", "icon": "100", "kind": "button"},
                {"id": "view.one_page", "label": "One", "icon": "▤", "kind": "button"},
                {"id": "view.multiple_pages", "label": "Multi", "icon": "▥", "kind": "button"},
                {"id": "view.page_width", "label": "Width", "icon": "↔", "kind": "button"},
            ]},
            {"title": "Window", "class_name": "group-view-window", "controls": [
                {"id": "view.new_window", "label": "New", "icon": "⊞", "kind": "button"},
                {"id": "view.arrange_all", "label": "Arrange", "icon": "☷", "kind": "button"},
                {"id": "view.split", "label": "Split", "icon": "▤", "kind": "button"},
                {"id": "view.view_side_by_side", "label": "Side", "icon": "⇔", "kind": "button"},
                {"id": "view.synchronous", "label": "Sync", "icon": "↕", "kind": "button"},
                {"id": "view.reset_position", "label": "Reset", "icon": "⌂", "kind": "button"},
                {"id": "view.switch_windows", "label": "Switch", "icon": "↻", "kind": "menu"},
            ]},
            {"title": "Macros", "class_name": "group-view-macros", "controls": [
                {"id": "view.macros", "label": "Macros", "icon": "▦", "kind": "menu"},
            ]},
            {"title": "SharePoint", "class_name": "group-view-sharepoint", "controls": [
                {"id": "view.properties", "label": "Properties", "icon": "S", "kind": "button"},
            ]},
        ]},
        {"id": "developer", "label": "Developer", "groups": [
            {"title": "Code", "class_name": "group-dev-code", "controls": [
                {"id": "developer.visual_basic", "label": "VB", "icon": "▣", "kind": "button"},
                {"id": "developer.macros", "label": "Macros", "icon": "▤", "kind": "button"},
                {"id": "developer.record_macro", "label": "Record", "icon": "●", "kind": "button"},
                {"id": "developer.macro_security", "label": "Security", "icon": "⚠", "kind": "button"},
            ]},
            {"title": "Add-ins", "class_name": "group-dev-addins", "controls": [
                {"id": "developer.addins", "label": "Add-ins", "icon": "⬡", "kind": "button"},
                {"id": "developer.word_addins", "label": "Word Add-ins", "icon": "⚙", "kind": "button"},
                {"id": "developer.com_addins", "label": "COM Add-ins", "icon": "▥", "kind": "button"},
            ]},
            {"title": "Controls", "class_name": "group-dev-controls", "controls": [
                {"id": "developer.design_mode", "label": "Design", "icon": "✎", "kind": "button"},
                {"id": "developer.properties", "label": "Properties", "icon": "☷", "kind": "button"},
                {"id": "developer.group", "label": "Group", "icon": "⊟", "kind": "button"},
            ]},
            {"title": "Mapping", "class_name": "group-dev-mapping", "controls": [
                {"id": "developer.xml_mapping", "label": "XML Mapping", "icon": "▦", "kind": "button"},
            ]},
            {"title": "Protect", "class_name": "group-dev-protect", "controls": [
                {"id": "developer.block_authors", "label": "Block", "icon": "👤", "kind": "button"},
                {"id": "developer.restrict_editing", "label": "Restrict", "icon": "🔒", "kind": "button"},
            ]},
            {"title": "Templates", "class_name": "group-dev-templates", "controls": [
                {"id": "developer.document_template", "label": "Template", "icon": "W", "kind": "button"},
            ]},
        ]},
        {"id": "help", "label": "Help", "groups": [
            {"title": "Help", "class_name": "group-review-language", "controls": [
                {"id": "help.search", "label": "Search", "icon": "⌕", "kind": "menu"},
                {"id": "help.training", "label": "Training", "icon": "▶", "kind": "button"},
            ]},
            {"title": "Support", "class_name": "group-review-accessibility", "controls": [
                {"id": "help.contact_support", "label": "Support", "icon": "💬", "kind": "button"},
            ]},
        ]},
        {"id": "acrobat", "label": "Acrobat", "groups": [
            {"title": "Adobe Acrobat", "class_name": "group-acrobat", "controls": [
                {"id": "acrobat.create_pdf", "label": "Create a PDF", "icon": "PDF", "kind": "button"},
                {"id": "acrobat.request_signatures", "label": "Request", "icon": "✍", "kind": "button"},
            ]},
        ]},
        {"id": "picture_format", "label": "Picture Format", "groups": [
            {"title": "Adjust", "class_name": "group-picture-adjust", "controls": [
                {"id": "picture_format.remove_bg", "label": "Remove BG", "icon": "⌫", "kind": "button"},
                {"id": "picture_format.corrections", "label": "Corrections", "icon": "◌", "kind": "menu"},
            ]},
            {"title": "Wrap Text", "class_name": "group-featured", "controls": [
                {"id": "picture_format.wrap_inline", "label": "Inline", "icon": "≡", "kind": "button", "action": "set_wrap:inline"},
                {"id": "picture_format.wrap_square", "label": "Square", "icon": "▣", "kind": "button", "action": "set_wrap:square"},
                {"id": "picture_format.wrap_tight", "label": "Tight", "icon": "▤", "kind": "button", "action": "set_wrap:tight"},
            ]},
            {"title": "Arrange", "class_name": "group-arrange", "controls": [
                {"id": "picture_format.align_left", "label": "Left", "icon": "⇤", "kind": "button", "action": "set_alignment:left"},
                {"id": "picture_format.align_center", "label": "Center", "icon": "↔", "kind": "button", "action": "set_alignment:center"},
                {"id": "picture_format.align_right", "label": "Right", "icon": "⇥", "kind": "button", "action": "set_alignment:right"},
            ]},
            {"title": "Size", "class_name": "group-wide", "controls": [
                {"id": "picture_format.size_small", "label": "Small", "icon": "◻", "kind": "button", "action": "set_size:small"},
                {"id": "picture_format.size_medium", "label": "Medium", "icon": "◼", "kind": "button", "action": "set_size:medium"},
                {"id": "picture_format.size_large", "label": "Large", "icon": "⬛", "kind": "button", "action": "set_size:large"},
            ]},
        ]},
    ]
    return {
        "app": "word",
        "mode": shell_mode,
        "inactive_controls_style": inactive_controls_style,
        "title": task_title,
        "tabs": tabs,
        "active_tabs": active_tabs,
        "active_controls": active_controls,
        "default_tab": "insert",
        "default_context_tab": "picture_format",
        "menus": {
            "insert.pictures": {
                "title": "Insert Picture",
                "description": "Choose an image to insert into the document."
            },
            "insert.table": {
                "title": "Table",
                "description": "Insert tables into your document. This control is visible for realism in this task."
            },
            "layout.wrap_text": {
                "title": "Wrap Text",
                "description": "Wrap text around objects. Use the Picture Format tab for this task."
            },
        },
    }


def build_html_shell(task_title, shell_mode="test"):
    return {
        "app": "html",
        "mode": shell_mode,
        "title": task_title,
        "editor_title": "index.html",
        "panes": ["instructions", "editor", "preview"],
        "theme": {
            "accent": "#e34c26",
            "editor_bg": "#1e1e1e",
            "preview_bg": "#ffffff",
        },
    }


def build_access_shell(task_title, simulator_type, shell_mode="test"):
    return {
        "app": "access",
        "mode": shell_mode,
        "title": task_title,
        "simulator_type": simulator_type,
        "accent": "#a4373a",
        "ribbon_tooltips": _load_ribbon_tooltip_map(ACCESS_RIBBON_LAYOUT_PATH),
    }


def build_excel_shell(task_title, simulator_type, shell_mode="test"):
    ribbon = _build_excel_ribbon_from_layout()
    return {
        "app": "excel",
        "mode": shell_mode,
        "title": task_title,
        "simulator_type": simulator_type,
        "accent": "#217346",
        "ribbon": ribbon,
        "ribbon_tooltips": _load_ribbon_tooltip_map(EXCEL_RIBBON_LAYOUT_PATH),
    }


def get_simulator_catalog():
    word_caps_active_controls = sorted(
        {
            step
            for item in WORD_CAPS_QUESTION_BANK
            for step in item.get("steps", [])
            if "." in step
        }
    )
    return {
        WORD_CAPS_PRACTICAL_KEY: {
            "title": "Word CAPS Practical Builder",
            "description": "Word-style practical simulator with one question at a time.",
            "shell": build_word_shell(
                "CAPS Word Practical",
                active_tabs=["home", "insert", "layout", "references", "mailings", "smartart_format", "table_layout"],
                active_controls=word_caps_active_controls,
                shell_mode="test",
                inactive_controls_style="enabled",
            ),
            "default_question_html": "<p>Complete each Word practical question one at a time.</p>",
        },
        WORD_INSERT_PICTURE_SIMULATOR_KEY: {
            "title": "Word: Insert a Picture",
            "description": "Simulates inserting and formatting a picture in a Word document.",
            "shell": build_word_shell(
                "Computer Lab Safety Procedures",
                active_tabs=["insert", "picture_format"],
                active_controls=[
                    "insert.pictures",
                    "picture_format.wrap_inline",
                    "picture_format.wrap_square",
                    "picture_format.wrap_tight",
                    "picture_format.align_left",
                    "picture_format.align_center",
                    "picture_format.align_right",
                    "picture_format.size_small",
                    "picture_format.size_medium",
                    "picture_format.size_large",
                ],
                shell_mode="test",
                inactive_controls_style="enabled",
            ),
            "criteria": [
                {"key": "opened_insert_menu", "label": "Open the Insert menu"},
                {"key": "selected_correct_image", "label": "Choose the required image"},
                {"key": "placed_below_heading", "label": "Place the image below the heading"},
                {"key": "set_wrap_square", "label": "Set text wrap to Square"},
                {"key": "set_alignment_center", "label": "Center-align the picture"},
                {"key": "set_size_medium", "label": "Resize the picture to Medium"},
            ],
            "image_options": [
                {"value": "network-diagram.png", "label": "network-diagram.png"},
                {"value": "computer-lab.jpg", "label": "computer-lab.jpg"},
                {"value": "school-logo.png", "label": "school-logo.png"},
            ],
            "correct_state": {
                "insert_menu_opened": "1",
                "selected_image": "computer-lab.jpg",
                "placement": "below_heading",
                "wrap": "square",
                "alignment": "center",
                "size": "medium",
            },
            "default_question_html": (
                "<p><strong>Task:</strong> Insert the provided lab image into the Word document and format it correctly.</p>"
                "<ol>"
                "<li>Open the <strong>Insert</strong> menu.</li>"
                "<li>Choose <strong>computer-lab.jpg</strong>.</li>"
                "<li>Place the image below the heading.</li>"
                "<li>Set text wrapping to <strong>Square</strong>.</li>"
                "<li>Center the image.</li>"
                "<li>Resize the image to <strong>Medium</strong>.</li>"
                "</ol>"
            ),
        },
        HTML_BASIC_PAGE_SIMULATOR_KEY: {
            "title": "HTML: Build a Basic Web Page",
            "description": "Learners build a simple HTML page inside the portal with live preview and rubric-based marking.",
            "shell": build_html_shell("My First Web Page", shell_mode="test"),
            "criteria": [
                {"key": "has_doctype", "label": "Include the HTML5 doctype"},
                {"key": "has_html_tag", "label": "Add the <html> root element"},
                {"key": "has_title", "label": "Set the page title to CAT Practice"},
                {"key": "has_h1", "label": "Add the heading Welcome to CAT"},
                {"key": "has_paragraph", "label": "Add the paragraph This is my first web page."},
                {"key": "has_image", "label": "Insert an image with alt text Computer lab"},
            ],
            "correct_state": {
                "title": "cat practice",
                "h1": "welcome to cat",
                "paragraph": "this is my first web page.",
                "image_alt": "computer lab",
            },
            "starter_code": """<!DOCTYPE html>
<html>
<head>
    <title>My Page</title>
</head>
<body>

</body>
</html>""",
            "default_question_html": (
                "<p><strong>Task:</strong> Build a basic HTML page in the editor.</p>"
                "<ol>"
                "<li>Add the <strong>HTML5 doctype</strong>.</li>"
                "<li>Set the page <strong>title</strong> to <strong>CAT Practice</strong>.</li>"
                "<li>Add an <strong>H1</strong> heading: <strong>Welcome to CAT</strong>.</li>"
                "<li>Add a paragraph: <strong>This is my first web page.</strong></li>"
                "<li>Insert an image with <strong>alt=\"Computer lab\"</strong>.</li>"
                "</ol>"
            ),
        },
        EXCEL_DATA_FORMULA_SIMULATOR_KEY: {
            "title": "Excel: Data Entry and Formula",
            "description": "Capture tabular data and create a formula using Excel-style autocomplete.",
            "shell": build_excel_shell("School Fees Register", "sheet_formula", shell_mode="test"),
            "criteria": [
                {"key": "headers", "label": "Enter the three headers: Name, Grade, Total money paid to school"},
                {"key": "ten_rows", "label": "Complete 10 rows of learner data"},
                {"key": "numeric_totals", "label": "Enter numeric amounts in the total paid column"},
                {"key": "selected_range", "label": "Select the amount cells before building the formula"},
                {"key": "sum_formula", "label": "Create a SUM formula for the selected amount range"},
            ],
            "default_question_html": (
                "<p><strong>Task:</strong> Complete the spreadsheet and calculate the total fees paid.</p>"
                "<ol>"
                "<li>Fill the first row with the headings <strong>Name</strong>, <strong>Grade</strong> and <strong>Total money paid to school</strong>.</li>"
                "<li>Capture <strong>10 rows</strong> of learner data underneath the headings.</li>"
                "<li>Select the payment cells in the third column.</li>"
                "<li>In the total row, start the formula with <strong>=</strong>, choose a formula from the suggestions, and calculate the overall total.</li>"
                "</ol>"
            ),
            "formula_suggestions": ["SUM", "AVERAGE", "MAX", "MIN", "COUNT", "IF"],
        },
        EXCEL_CHART_CAPTION_SIMULATOR_KEY: {
            "title": "Excel: Insert Chart and Edit Caption",
            "description": "Insert a chart from worksheet data and edit the chart caption.",
            "shell": build_excel_shell("Learner Payments Chart", "chart_caption", shell_mode="test"),
            "criteria": [
                {"key": "selected_chart_range", "label": "Select the learner names and payment amounts"},
                {"key": "chart_inserted", "label": "Insert a chart into the worksheet"},
                {"key": "caption_updated", "label": "Edit the chart caption to School Fees by Learner"},
            ],
            "default_question_html": (
                "<p><strong>Task:</strong> Insert a chart and update its caption.</p>"
                "<ol>"
                "<li>Select the learner names and payment amounts in the worksheet.</li>"
                "<li>Insert a chart from the selected data.</li>"
                "<li>Change the chart caption to <strong>School Fees by Learner</strong>.</li>"
                "</ol>"
            ),
            "chart_rows": [
                ("Aiden", 1250),
                ("Bianca", 980),
                ("Caleb", 1430),
                ("Dineo", 1100),
                ("Ethan", 1560),
            ],
        },
        ACCESS_TABLE_SIMULATOR_KEY: {
            "title": "Access: Create Table Design",
            "description": "Create a table structure with correct field properties.",
            "shell": build_access_shell("Learners Table", "table", shell_mode="test"),
            "criteria": [
                {"key": "table_name", "label": "Name the table Learners"},
                {"key": "field_learnerid", "label": "Add LearnerID as AutoNumber primary key"},
                {"key": "field_surname", "label": "Add Surname as Short Text and set Required to Yes"},
                {"key": "field_grade", "label": "Add Grade as Number with field size Byte"},
            ],
            "default_question_html": (
                "<p><strong>Task:</strong> Create a table called <strong>Learners</strong>.</p>"
                "<ol>"
                "<li>Add <strong>LearnerID</strong> as <strong>AutoNumber</strong> and make it the <strong>Primary Key</strong>.</li>"
                "<li>Add <strong>Surname</strong> as <strong>Short Text</strong> and set <strong>Required</strong> to <strong>Yes</strong>.</li>"
                "<li>Add <strong>Grade</strong> as <strong>Number</strong> with field size <strong>Byte</strong>.</li>"
                "</ol>"
            ),
        },
        ACCESS_QUERY_SIMULATOR_KEY: {
            "title": "Access: Build Select Query",
            "description": "Build a filtered and sorted select query.",
            "shell": build_access_shell("Grade 10 Learners Query", "query", shell_mode="test"),
            "criteria": [
                {"key": "query_name", "label": "Name the query Grade10Learners"},
                {"key": "source_table", "label": "Use Learners as the source table"},
                {"key": "fields", "label": "Select Surname and Grade fields"},
                {"key": "criteria", "label": "Filter records where Grade = 10"},
                {"key": "sort", "label": "Sort Surname in ascending order"},
            ],
            "default_question_html": (
                "<p><strong>Task:</strong> Create a select query called <strong>Grade10Learners</strong>.</p>"
                "<ol>"
                "<li>Use the <strong>Learners</strong> table.</li>"
                "<li>Display only <strong>Surname</strong> and <strong>Grade</strong>.</li>"
                "<li>Show only records where <strong>Grade = 10</strong>.</li>"
                "<li>Sort <strong>Surname</strong> in <strong>Ascending</strong> order.</li>"
                "</ol>"
            ),
        },
        ACCESS_FORM_SIMULATOR_KEY: {
            "title": "Access: Create Data Entry Form",
            "description": "Build a simple bound form layout.",
            "shell": build_access_shell("Learner Entry Form", "form", shell_mode="test"),
            "criteria": [
                {"key": "form_name", "label": "Name the form frmLearners"},
                {"key": "record_source", "label": "Use Learners as the record source"},
                {"key": "controls", "label": "Add controls for Surname, Name and Grade"},
                {"key": "title", "label": "Set the form heading to Learner Details"},
                {"key": "layout", "label": "Use a stacked layout"},
            ],
            "default_question_html": (
                "<p><strong>Task:</strong> Create a form called <strong>frmLearners</strong>.</p>"
                "<ol>"
                "<li>Use the <strong>Learners</strong> table as the record source.</li>"
                "<li>Add fields for <strong>Surname</strong>, <strong>Name</strong> and <strong>Grade</strong>.</li>"
                "<li>Set the heading to <strong>Learner Details</strong>.</li>"
                "<li>Use a <strong>Stacked</strong> layout.</li>"
                "</ol>"
            ),
        },
        ACCESS_REPORT_SIMULATOR_KEY: {
            "title": "Access: Create Summary Report",
            "description": "Build a grouped report layout with totals.",
            "shell": build_access_shell("Learners by Grade Report", "report", shell_mode="test"),
            "criteria": [
                {"key": "report_name", "label": "Name the report rptLearnersByGrade"},
                {"key": "record_source", "label": "Use Learners as the report source"},
                {"key": "grouping", "label": "Group the report by Grade"},
                {"key": "fields", "label": "Show Surname and Grade in the detail section"},
                {"key": "total", "label": "Add a record count in the report footer"},
            ],
            "default_question_html": (
                "<p><strong>Task:</strong> Create a report called <strong>rptLearnersByGrade</strong>.</p>"
                "<ol>"
                "<li>Use the <strong>Learners</strong> table as the source.</li>"
                "<li>Group the report by <strong>Grade</strong>.</li>"
                "<li>Show <strong>Surname</strong> and <strong>Grade</strong> in the detail section.</li>"
                "<li>Add a <strong>record count</strong> in the footer.</li>"
                "</ol>"
            ),
        },
    }


def get_simulator_definition(simulator_key):
    return get_simulator_catalog().get(simulator_key)


def score_simulator_attempt(simulator_key, form_data):
    definition = get_simulator_definition(simulator_key)
    if not definition:
        return None

    if simulator_key == HTML_BASIC_PAGE_SIMULATOR_KEY:
        html_code = (form_data.get("html_code") or "").strip()
        html_lower = html_code.lower()
        correct_state = definition["correct_state"]

        title_match = re.search(r"<title>\s*(.*?)\s*</title>", html_code, re.IGNORECASE | re.DOTALL)
        h1_match = re.search(r"<h1[^>]*>\s*(.*?)\s*</h1>", html_code, re.IGNORECASE | re.DOTALL)
        paragraph_match = re.search(r"<p[^>]*>\s*(.*?)\s*</p>", html_code, re.IGNORECASE | re.DOTALL)
        image_alt_match = re.search(r"<img[^>]*\balt\s*=\s*['\"](.*?)['\"]", html_code, re.IGNORECASE | re.DOTALL)

        checks = [
            ("has_doctype", "<!doctype html>" in html_lower),
            ("has_html_tag", bool(re.search(r"<html\b", html_lower))),
            ("has_title", (title_match.group(1).strip().lower() if title_match else "") == correct_state["title"]),
            ("has_h1", (h1_match.group(1).strip().lower() if h1_match else "") == correct_state["h1"]),
            ("has_paragraph", (paragraph_match.group(1).strip().lower() if paragraph_match else "") == correct_state["paragraph"]),
            ("has_image", bool(re.search(r"<img\b", html_lower)) and (image_alt_match.group(1).strip().lower() if image_alt_match else "") == correct_state["image_alt"]),
        ]

        results = []
        score = 0
        for key, passed in checks:
            criterion = next(item for item in definition["criteria"] if item["key"] == key)
            if passed:
                score += 1
            results.append(
                {
                    "question": criterion["label"],
                    "passed": passed,
                    "marks_awarded": 1 if passed else 0,
                    "marks_available": 1,
                }
            )

        total = len(results)
        percentage = round((score / total) * 100) if total else 0
        return {
            "score": score,
            "total": total,
            "percentage": percentage,
            "results": results,
            "state": {"html_code": html_code},
            "definition": definition,
        }

    if simulator_key == EXCEL_DATA_FORMULA_SIMULATOR_KEY:
        headers = [
            (form_data.get("cell_A1") or "").strip().lower(),
            (form_data.get("cell_B1") or "").strip().lower(),
            (form_data.get("cell_C1") or "").strip().lower(),
        ]
        rows = []
        for row in range(2, 12):
            rows.append(
                {
                    "name": (form_data.get(f"cell_A{row}") or "").strip(),
                    "grade": (form_data.get(f"cell_B{row}") or "").strip(),
                    "amount": (form_data.get(f"cell_C{row}") or "").strip(),
                }
            )
        formula_text = (form_data.get("formula_input") or "").strip().upper().replace(" ", "")
        selected_range = (form_data.get("selected_range") or "").strip().upper()
        filled_rows = [row for row in rows if row["name"] and row["grade"] and row["amount"]]
        numeric_amounts = all(row["amount"].replace(".", "", 1).isdigit() for row in filled_rows) and len(filled_rows) == 10
        checks = [
            ("headers", headers == ["name", "grade", "total money paid to school"]),
            ("ten_rows", len(filled_rows) == 10),
            ("numeric_totals", numeric_amounts),
            ("selected_range", selected_range == "C2:C11"),
            ("sum_formula", formula_text in {"=SUM(C2:C11)", "=SUM(C2:C11"} or formula_text.startswith("=SUM(")),
        ]
    elif simulator_key == EXCEL_CHART_CAPTION_SIMULATOR_KEY:
        selected_range = (form_data.get("selected_chart_range") or "").strip().upper()
        chart_inserted = (form_data.get("chart_inserted") or "").strip() == "1"
        caption = (form_data.get("chart_caption") or "").strip().lower()
        checks = [
            ("selected_chart_range", selected_range == "A2:B6"),
            ("chart_inserted", chart_inserted),
            ("caption_updated", caption == "school fees by learner"),
        ]
    else:
        checks = None

    if checks is None and simulator_key == ACCESS_TABLE_SIMULATOR_KEY:
        table_name = (form_data.get("table_name") or "").strip().lower()
        fields = []
        for idx in range(1, 4):
            fields.append(
                {
                    "name": (form_data.get(f"field_name_{idx}") or "").strip().lower(),
                    "type": (form_data.get(f"field_type_{idx}") or "").strip().lower(),
                    "pk": form_data.get("primary_key_field") == str(idx),
                    "required": form_data.get(f"required_{idx}") == "on",
                    "size": (form_data.get(f"field_size_{idx}") or "").strip().lower(),
                }
            )
        checks = [
            ("table_name", table_name == "learners"),
            ("field_learnerid", any(f["name"] == "learnerid" and f["type"] == "autonumber" and f["pk"] for f in fields)),
            ("field_surname", any(f["name"] == "surname" and f["type"] == "short text" and f["required"] for f in fields)),
            ("field_grade", any(f["name"] == "grade" and f["type"] == "number" and f["size"] == "byte" for f in fields)),
        ]
    elif simulator_key == ACCESS_QUERY_SIMULATOR_KEY:
        selected_fields = {value.lower() for value in form_data.getlist("query_fields")}
        checks = [
            ("query_name", (form_data.get("query_name") or "").strip().lower() == "grade10learners"),
            ("source_table", (form_data.get("source_table") or "").strip().lower() == "learners"),
            ("fields", selected_fields == {"surname", "grade"}),
            ("criteria", (form_data.get("criteria_field") or "").strip().lower() == "grade" and (form_data.get("criteria_value") or "").strip() == "10"),
            ("sort", (form_data.get("sort_field") or "").strip().lower() == "surname" and (form_data.get("sort_order") or "").strip().lower() == "ascending"),
        ]
    elif simulator_key == ACCESS_FORM_SIMULATOR_KEY:
        controls = {value.lower() for value in form_data.getlist("form_controls")}
        checks = [
            ("form_name", (form_data.get("form_name") or "").strip().lower() == "frmlearners"),
            ("record_source", (form_data.get("form_source") or "").strip().lower() == "learners"),
            ("controls", controls == {"surname", "name", "grade"}),
            ("title", (form_data.get("form_title") or "").strip().lower() == "learner details"),
            ("layout", (form_data.get("form_layout") or "").strip().lower() == "stacked"),
        ]
    elif simulator_key == ACCESS_REPORT_SIMULATOR_KEY:
        detail_fields = {value.lower() for value in form_data.getlist("report_fields")}
        checks = [
            ("report_name", (form_data.get("report_name") or "").strip().lower() == "rptlearnersbygrade"),
            ("record_source", (form_data.get("report_source") or "").strip().lower() == "learners"),
            ("grouping", (form_data.get("group_by") or "").strip().lower() == "grade"),
            ("fields", detail_fields == {"surname", "grade"}),
            ("total", (form_data.get("footer_total") or "").strip().lower() == "record count"),
        ]
    elif checks is None:
        checks = None

    if checks is not None:
        results = []
        score = 0
        for key, passed in checks:
            criterion = next(item for item in definition["criteria"] if item["key"] == key)
            if passed:
                score += 1
            results.append(
                {
                    "question": criterion["label"],
                    "passed": passed,
                    "marks_awarded": 1 if passed else 0,
                    "marks_available": 1,
                }
            )
        total = len(results)
        percentage = round((score / total) * 100) if total else 0
        return {
            "score": score,
            "total": total,
            "percentage": percentage,
            "results": results,
            "state": dict(form_data),
            "definition": definition,
        }

    state = {
        "insert_menu_opened": form_data.get("insert_menu_opened", ""),
        "selected_image": form_data.get("selected_image", ""),
        "placement": form_data.get("placement", ""),
        "wrap": form_data.get("wrap", ""),
        "alignment": form_data.get("alignment", ""),
        "size": form_data.get("size", ""),
    }
    correct_state = definition["correct_state"]

    checks = [
        ("opened_insert_menu", state["insert_menu_opened"] == correct_state["insert_menu_opened"]),
        ("selected_correct_image", state["selected_image"] == correct_state["selected_image"]),
        ("placed_below_heading", state["placement"] == correct_state["placement"]),
        ("set_wrap_square", state["wrap"] == correct_state["wrap"]),
        ("set_alignment_center", state["alignment"] == correct_state["alignment"]),
        ("set_size_medium", state["size"] == correct_state["size"]),
    ]

    results = []
    score = 0
    for key, passed in checks:
        criterion = next(item for item in definition["criteria"] if item["key"] == key)
        if passed:
            score += 1
        results.append(
            {
                "question": criterion["label"],
                "passed": passed,
                "marks_awarded": 1 if passed else 0,
                "marks_available": 1,
            }
        )

    total = len(results)
    percentage = round((score / total) * 100) if total else 0
    return {
        "score": score,
        "total": total,
        "percentage": percentage,
        "results": results,
        "state": state,
        "definition": definition,
    }
