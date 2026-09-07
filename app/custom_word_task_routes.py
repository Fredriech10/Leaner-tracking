"""Teacher-facing no-code builder for Word upload tasks."""

import json
import os
import tempfile
import hashlib
from datetime import datetime

from flask import redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from app.database import get_db, get_marking_db, get_teachers, get_user_role, log_activity
from marking.tasks.marking_experiment_adapter import mark_with_setup

FONT_NAMES = (
    "Arial", "Calibri", "Cambria", "Century Gothic", "Comic Sans MS", "Courier New",
    "Georgia", "Impact", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana",
)
COLOUR_NAMES = ("black", "blue", "green", "red", "yellow", "white", "grey", "light grey")
BORDER_STYLES = ("single", "double", "dotted", "dashed", "thick", "triple", "wave")
PAGE_COLOURS = ("FFFFFF", "000000", "0000FF", "0070C0", "00B050", "FF0000", "FFFF00", "D9D9D9")
SECTION_BREAK_TYPES = ("nextPage", "continuous", "evenPage", "oddPage")


RULES = {
    # These definitions deliberately mirror checks in Marking_Experiment.word_checker.
    # The form renders the fields from this catalogue; no teacher-authored Python is needed.
    "font_name": {"group": "Font", "label": "Font name", "domain": "font", "check_type": "font_name", "target": "text", "layout": "value", "value_label": "Font name", "placeholder": "e.g. Arial"},
    "font_size": {"group": "Font", "label": "Font size", "domain": "font", "check_type": "size", "target": "text", "layout": "number", "value_label": "Size (pt)", "placeholder": "e.g. 16"},
    "font_color": {"group": "Font", "label": "Font colour", "domain": "font", "check_type": "color", "target": "text", "layout": "value", "value_label": "Colour", "placeholder": "e.g. blue or 0070C0"},
    "bold": {"group": "Font", "label": "Bold", "domain": "font", "check_type": "bold", "target": "text", "layout": "boolean"},
    "italic": {"group": "Font", "label": "Italic", "domain": "font", "check_type": "italic", "target": "text", "layout": "boolean"},
    "underline": {"group": "Font", "label": "Underline", "domain": "font", "check_type": "underline", "target": "text", "layout": "boolean"},
    "underline_style": {"group": "Font", "label": "Underline style", "domain": "font", "check_type": "underline_style", "target": "text", "layout": "underline_style"},
    "strikethrough": {"group": "Font", "label": "Strikethrough", "domain": "font", "check_type": "strikethrough", "target": "text", "layout": "boolean"},
    "superscript": {"group": "Font", "label": "Superscript", "domain": "font", "check_type": "superscript", "target": "text", "layout": "boolean"},
    "subscript": {"group": "Font", "label": "Subscript", "domain": "font", "check_type": "subscript", "target": "text", "layout": "boolean"},
    "all_caps": {"group": "Font", "label": "All caps", "domain": "font", "check_type": "all_caps", "target": "text", "layout": "boolean"},
    "small_caps": {"group": "Font", "label": "Small caps", "domain": "font", "check_type": "small_caps", "target": "text", "layout": "boolean"},
    "character_spacing": {"group": "Font", "label": "Character spacing", "domain": "font", "check_type": "character_spacing", "target": "text", "layout": "number", "value_label": "Spacing (pt)", "placeholder": "e.g. 3"},
    "alignment": {"group": "Paragraph", "label": "Paragraph alignment", "domain": "paragraph_formatting", "check_type": "alignment", "target": "text", "layout": "alignment"},
    "line_spacing": {"group": "Paragraph", "label": "Line spacing", "domain": "paragraph_formatting", "check_type": "line_spacing", "target": "text", "layout": "line_spacing"},
    "space_before": {"group": "Paragraph", "label": "Spacing before", "domain": "paragraph_formatting", "check_type": "space_before", "target": "text", "layout": "number", "value_label": "Spacing before (pt)", "placeholder": "e.g. 12"},
    "space_after": {"group": "Paragraph", "label": "Spacing after", "domain": "paragraph_formatting", "check_type": "space_after", "target": "text", "layout": "number", "value_label": "Spacing after (pt)", "placeholder": "e.g. 6"},
    "first_line_indent": {"group": "Paragraph", "label": "First-line indent", "domain": "paragraph_formatting", "check_type": "first_line_indent", "target": "text", "layout": "number", "value_label": "First-line indent (cm)", "placeholder": "e.g. 0.5"},
    "hanging_indent": {"group": "Paragraph", "label": "Hanging indent", "domain": "paragraph_formatting", "check_type": "hanging_indent", "target": "text", "layout": "number", "value_label": "Hanging indent (cm)", "placeholder": "e.g. 1.27"},
    "left_indent": {"group": "Paragraph", "label": "Left indent", "domain": "paragraph_formatting", "check_type": "left_indent", "target": "text", "layout": "number", "value_label": "Left indent (cm)", "placeholder": "e.g. 1.5"},
    "right_indent": {"group": "Paragraph", "label": "Right indent", "domain": "paragraph_formatting", "check_type": "right_indent", "target": "text", "layout": "number", "value_label": "Right indent (cm)", "placeholder": "e.g. 1.5"},
    "paragraph_border": {"group": "Paragraph", "label": "Paragraph border", "domain": "paragraph_formatting", "check_type": "border", "target": "text", "layout": "paragraph_border"},
    "paragraph_shading": {"group": "Paragraph", "label": "Paragraph shading", "domain": "paragraph_formatting", "check_type": "shading", "target": "text", "layout": "paragraph_shading", "value_label": "Shading colour", "placeholder": "e.g. light grey or yellow"},
    "drop_cap": {"group": "Paragraph", "label": "Drop cap", "domain": "paragraph_formatting", "check_type": "drop_cap", "target": "text", "layout": "boolean"},
    "paper_size": {"group": "Page layout", "label": "Paper size", "domain": "document", "check_type": "paper_size", "target": "none", "layout": "paper_size"},
    "orientation": {"group": "Page layout", "label": "Page orientation", "domain": "document", "check_type": "orientation", "target": "none", "layout": "orientation"},
    "margins": {"group": "Page layout", "label": "Custom margins", "domain": "document", "check_type": "margins", "target": "none", "layout": "margins"},
    "page_border": {"group": "Page layout", "label": "Page border", "domain": "document", "check_type": "page_border", "target": "none", "layout": "page_border"},
    "page_color": {"group": "Page layout", "label": "Page colour", "domain": "document", "check_type": "page_color", "target": "none", "layout": "value", "value_label": "Colour", "placeholder": "e.g. FFFF00"},
    "cover_page": {"group": "Page layout", "label": "Cover page fields", "domain": "document", "check_type": "cover_page_fields", "target": "none", "layout": "cover_page"},
    "cover_page_controls": {"group": "Page layout", "label": "Completed cover-page controls", "domain": "document", "check_type": "no_empty_content_controls", "target": "none", "layout": "boolean"},
    "cover_page_control_layout": {"group": "Page layout", "label": "Cover-page title and author controls", "domain": "document", "check_type": "cover_page_controls", "target": "none", "layout": "control_aliases"},
    "page_break": {"group": "Page layout", "label": "Page breaks", "domain": "document", "check_type": "page_break", "target": "none", "layout": "number", "value_label": "Number of page breaks", "placeholder": "e.g. 1"},
    "section_break": {"group": "Page layout", "label": "Section break", "domain": "document", "check_type": "section_page_break_type", "target": "none", "layout": "value", "value_label": "Break type", "placeholder": "e.g. nextPage or continuous"},
    "columns": {"group": "Page layout", "label": "Document columns", "domain": "document", "check_type": "columns", "target": "none", "layout": "columns"},
    "column_breaks": {"group": "Page layout", "label": "Column breaks", "domain": "document", "check_type": "column_breaks", "target": "none", "layout": "number", "value_label": "Minimum column breaks", "placeholder": "e.g. 3"},
    "hyphenation": {"group": "Page layout", "label": "Automatic hyphenation", "domain": "document", "check_type": "hyphenation", "target": "none", "layout": "boolean"},
    "watermark": {"group": "Page layout", "label": "Watermark text or layout", "domain": "document", "check_type": "watermark", "target": "none", "layout": "value", "value_label": "Watermark text, colour or layout", "placeholder": "e.g. CONFIDENTIAL, blue or diagonal"},
    "contains_date": {"group": "Page layout", "label": "Date inserted", "domain": "document", "check_type": "contains_date", "target": "none", "layout": "boolean"},
    "header_text": {"group": "Header and footer", "label": "Header text", "domain": "document", "check_type": "header_text", "target": "none", "layout": "value", "value_label": "Header must contain", "placeholder": "e.g. Name and surname"},
    "header_alignment": {"group": "Header and footer", "label": "Header alignment", "domain": "document", "check_type": "header_alignment", "target": "none", "layout": "alignment"},
    "footer_text": {"group": "Header and footer", "label": "Footer text", "domain": "document", "check_type": "footer_text", "target": "none", "layout": "value", "value_label": "Footer must contain", "placeholder": "e.g. Page X of Y"},
    "footer_alignment": {"group": "Header and footer", "label": "Footer alignment", "domain": "document", "check_type": "footer_alignment", "target": "none", "layout": "alignment"},
    "page_number_footer": {"group": "Header and footer", "label": "Page number in footer", "domain": "document", "check_type": "page_number_in_footer", "target": "none", "layout": "boolean"},
    "page_number_header": {"group": "Header and footer", "label": "Page number in header", "domain": "document", "check_type": "page_number_in_header", "target": "none", "layout": "boolean"},
    "document_property": {"group": "Document information", "label": "Document property", "domain": "document", "check_type": "document_property", "target": "none", "layout": "document_property"},
    "comment": {"group": "Review", "label": "Comment", "domain": "document", "check_type": "comments", "target": "none", "layout": "value", "value_label": "Comment must contain", "placeholder": "e.g. Check the source"},
    "find_replace": {"group": "Editing", "label": "Find and replace outcome", "domain": "document", "check_type": "find_replace", "target": "none", "layout": "find_replace"},
    "table_cell_text": {"group": "Tables", "label": "Table cell text", "domain": "table", "check_type": "cell_text", "target": "table", "layout": "table_cell_text"},
    "table_cell_alignment": {"group": "Tables", "label": "Table cell alignment", "domain": "table", "check_type": "cell_alignment", "target": "table", "layout": "table_cell_alignment"},
    "table_merge": {"group": "Tables", "label": "Merge table cells", "domain": "table", "check_type": "merge_horizontal", "target": "table", "layout": "table_merge"},
    "table_dimensions": {"group": "Tables", "label": "Inserted table size", "domain": "table", "check_type": "dimensions", "target": "table", "layout": "table_dimensions"},
    "table_borders": {"group": "Tables", "label": "Table borders", "domain": "table", "check_type": "borders", "target": "table", "layout": "boolean"},
    "table_border_details": {"group": "Tables", "label": "Table outside-border style", "domain": "table", "check_type": "border_details", "target": "table", "layout": "paragraph_border"},
    "table_row_shading": {"group": "Tables", "label": "Table row shading", "domain": "table", "check_type": "row_shading", "target": "table", "layout": "table_row_shading"},
    "table_row_height": {"group": "Tables", "label": "Table row height", "domain": "table", "check_type": "row_height", "target": "table", "layout": "table_row_height"},
    "table_row_change": {"group": "Tables", "label": "Rows added or removed from starter table", "domain": "table", "check_type": "row_count_change", "target": "table", "layout": "row_change"},
    "table_vertical_alignment": {"group": "Tables", "label": "Table cell vertical alignment", "domain": "table", "check_type": "cell_vertical_alignment", "target": "table", "layout": "table_vertical_alignment"},
    "table_text_direction": {"group": "Tables", "label": "Table cell text direction", "domain": "table", "check_type": "cell_text_direction", "target": "table", "layout": "table_text_direction"},
    "image_count": {"group": "Pictures and objects", "label": "Inserted picture count", "domain": "object", "check_type": "image_count", "target": "none", "layout": "number", "value_label": "Minimum pictures", "placeholder": "e.g. 1"},
    "image_width": {"group": "Pictures and objects", "label": "Picture width", "domain": "object", "check_type": "image_width", "target": "none", "layout": "number", "value_label": "Width (cm)", "placeholder": "e.g. 8"},
    "image_border": {"group": "Pictures and objects", "label": "Picture border", "domain": "object", "check_type": "image_border", "target": "none", "layout": "image_border"},
    "image_caption": {"group": "Pictures and objects", "label": "Picture caption", "domain": "object", "check_type": "caption_text", "target": "none", "layout": "value", "value_label": "Caption must contain", "placeholder": "e.g. Figure 1: Tourism"},
    "image_changed": {"group": "Pictures and objects", "label": "Starter picture replaced", "domain": "object", "check_type": "image_changed_from_starter", "target": "none", "layout": "boolean"},
    "image_matches_reference": {"group": "Pictures and objects", "label": "Picture matches reference image", "domain": "object", "check_type": "image_matches_reference", "target": "none", "layout": "boolean"},
    "textbox_count": {"group": "Pictures and objects", "label": "Inserted text box count", "domain": "object", "check_type": "textbox_count", "target": "none", "layout": "number", "value_label": "Minimum text boxes", "placeholder": "e.g. 1"},
    "textbox_text": {"group": "Pictures and objects", "label": "Text box content", "domain": "object", "check_type": "textbox_text", "target": "none", "layout": "value", "value_label": "Text box must contain", "placeholder": "e.g. Contact us today"},
    "textbox_shadow": {"group": "Pictures and objects", "label": "Text box shadow effect", "domain": "object", "check_type": "textbox_shadow", "target": "none", "layout": "boolean"},
    "textbox_position": {"group": "Pictures and objects", "label": "Text box position", "domain": "object", "check_type": "textbox_position", "target": "none", "layout": "textbox_position"},
    "textbox_style": {"group": "Pictures and objects", "label": "Text box paragraph style", "domain": "object", "check_type": "textbox_style", "target": "none", "layout": "style"},
    "smartart": {"group": "Pictures and objects", "label": "Inserted SmartArt", "domain": "object", "check_type": "smartart", "target": "none", "layout": "boolean"},
    "smartart_text": {"group": "Pictures and objects", "label": "SmartArt text", "domain": "object", "check_type": "smartart_text", "target": "none", "layout": "value", "value_label": "SmartArt must contain", "placeholder": "Separate terms with commas"},
    "list_style": {"group": "Lists", "label": "Bulleted or numbered list", "domain": "list", "check_type": "list_style", "target": "text", "layout": "list_style"},
    "list_indent": {"group": "Lists", "label": "List indent level", "domain": "list", "check_type": "indent_level", "target": "text", "layout": "number", "value_label": "Indent level", "placeholder": "e.g. 1"},
    "list_number_format": {"group": "Lists", "label": "Numbered-list format", "domain": "list", "check_type": "number_format", "target": "text", "layout": "number_format"},
    "list_item_count": {"group": "Lists", "label": "Minimum list items", "domain": "list", "check_type": "item_count", "target": "text", "layout": "number", "value_label": "Minimum items", "placeholder": "e.g. 4"},
    "picture_bullet": {"group": "Lists", "label": "Picture bullet / bullet character", "domain": "list", "check_type": "bullet_char", "target": "text", "layout": "bullet_char"},
    "bookmark": {"group": "References", "label": "Bookmark", "domain": "advanced", "check_type": "bookmark", "target": "none", "layout": "value", "value_label": "Bookmark name", "placeholder": "e.g. Introduction"},
    "bibliography": {"group": "References", "label": "Sources / bibliography", "domain": "advanced", "check_type": "bibliography", "target": "none", "layout": "number", "value_label": "Minimum sources", "placeholder": "e.g. 2"},
    "footnote": {"group": "References", "label": "Footnote text", "domain": "document", "check_type": "footnote_text", "target": "none", "layout": "value", "value_label": "Footnote must contain", "placeholder": "e.g. Source: Statistics SA"},
    "table_of_contents": {"group": "References", "label": "Automatic table of contents", "domain": "document", "check_type": "table_of_contents", "target": "none", "layout": "boolean"},
    "heading_style": {"group": "Styles", "label": "Heading or paragraph style", "domain": "advanced", "check_type": "style_applied", "target": "text", "layout": "style"},
    "heading_numbering": {"group": "Styles", "label": "Heading numbering format", "domain": "document", "check_type": "heading_number_format", "target": "text", "layout": "number_format"},
    "mail_merge_fields": {"group": "Mail merge", "label": "Mail merge fields", "domain": "document", "check_type": "mail_merge_fields", "target": "none", "layout": "merge_fields"},
    "mail_merge_source": {"group": "Mail merge", "label": "Mail merge data source", "domain": "document", "check_type": "mail_merge_source", "target": "none", "layout": "value", "value_label": "Data source filename", "placeholder": "e.g. Client List.xlsx"},
    "hyperlink_url": {"group": "References", "label": "Hyperlink web address", "domain": "object", "check_type": "hyperlink_url", "target": "none", "layout": "value", "value_label": "URL must contain", "placeholder": "e.g. wikipedia.org"},
    "hyperlink_text": {"group": "References", "label": "Hyperlink display text", "domain": "object", "check_type": "hyperlink_text", "target": "none", "layout": "value", "value_label": "Link text must contain", "placeholder": "e.g. Visit the website"},
    "cross_reference": {"group": "References", "label": "Cross-reference target", "domain": "advanced", "check_type": "cross_reference", "target": "none", "layout": "value", "value_label": "Referenced bookmark", "placeholder": "e.g. Introduction"},
    "citation": {"group": "References", "label": "Citation source tag", "domain": "document", "check_type": "citation_field", "target": "none", "layout": "value", "value_label": "Citation source tag", "placeholder": "e.g. Smith2025"},
    "text_present": {"group": "Editing", "label": "Required text or symbol", "domain": "document", "check_type": "contains_text", "target": "none", "layout": "value", "value_label": "Text or symbol that must appear", "placeholder": "e.g. ®"},
    "no_repeated_spaces": {"group": "Editing", "label": "Remove repeated spaces", "domain": "document", "check_type": "no_repeated_spaces", "target": "none", "layout": "boolean"},
}


def _rule_from_form(index):
    rule_key = request.form.get(f"rule_{index}", "")
    description = request.form.get(f"description_{index}", "").strip()
    target_text = request.form.get(f"target_{index}", "").strip()
    values = {name: request.form.get(f"{name}_{index}", "").strip() for name in (
        "value", "value_2", "value_3", "row", "column", "column_end", "top", "bottom", "left", "right", "line_rule", "line_unit", "list_type", "list_level", "tolerance"
    )}
    marks = max(1, int(request.form.get(f"marks_{index}", "1") or 1))
    if not description or rule_key not in RULES:
        return None

    definition = RULES[rule_key]
    if definition["target"] == "text" and not target_text:
        raise ValueError(f"Criterion {index + 1} needs target text to locate the change.")

    target = {}
    if definition["target"] == "text":
        target = {"locator": "contains_text", "value": target_text}
    elif definition["target"] == "table":
        target = {"locator": "table_index", "value": max(0, int(target_text or "1") - 1)}

    layout = definition["layout"]
    expected = values["value"]
    if rule_key == "bibliography":
        expected = {"source_count": int(values["value"])}
    elif layout == "number":
        expected = float(values["value"])
    elif layout == "boolean":
        expected = values["value"].lower() not in {"false", "no", "0"}
    elif layout == "alignment":
        expected = values["value"].lower()
    elif layout == "line_spacing":
        expected = {"rule": values["line_rule"], "value": float(values["value"]), "unit": values["line_unit"]}
    elif layout == "margins":
        expected = {side: float(values[side]) for side in ("top", "bottom", "left", "right")}
    elif layout == "page_border":
        expected = {"style": values["value"], "color": values["value_2"], "first_page_only": values["value_3"].lower() in {"true", "yes", "1"}}
    elif layout == "paragraph_border":
        expected = {"style": values["value"], "color": values["value_2"], "width_pt": float(values["value_3"])}
    elif layout == "paragraph_shading":
        expected = {"color": values["value"]}
    elif layout == "table_cell_text":
        expected = {"row": int(values["row"]) - 1, "col": int(values["column"]) - 1, "text": values["value"], "tolerance": values["tolerance"].lower() in {"true", "yes", "1"}}
    elif layout == "table_cell_alignment":
        expected = {"row": int(values["row"]) - 1, "col": int(values["column"]) - 1, "horizontal": values["value"].lower()}
    elif layout == "table_merge":
        expected = {"row": int(values["row"]) - 1, "col_start": int(values["column"]) - 1, "col_end": int(values["column_end"]) - 1}
    elif layout == "table_dimensions":
        expected = {"rows": int(values["row"]), "columns": int(values["column"])}
    elif layout == "table_row_shading":
        expected = {"row": int(values["row"]) - 1, "color": values["value"]}
    elif layout == "image_border":
        expected = {"width_pt": float(values["value"]), "color": values["value_2"]}
    elif layout == "document_property":
        expected = {"property": values["value"], "value": values["value_2"]}
    elif layout == "cover_page":
        expected = {name: values[name] for name in ("value", "value_2", "value_3")}
        expected = {"title": expected["value"], "author": expected["value_2"], "abstract": expected["value_3"]}
    elif layout == "columns":
        expected = {"count": int(values["value"]), "space_cm": float(values["value_2"])}
    elif layout == "find_replace":
        expected = {"find": values["value"], "replace": values["value_2"], "minimum_replacements": int(values["value_3"])}
    elif layout == "table_row_height":
        expected = {"row": int(values["row"]) - 1, "height_cm": float(values["value"])}
    elif layout == "row_change":
        expected = {"delta": int(values["value"])}
    elif layout == "table_vertical_alignment":
        expected = {"row": int(values["row"]) - 1, "col": int(values["column"]) - 1, "vertical": values["value"]}
    elif layout == "table_text_direction":
        expected = {"row": int(values["row"]) - 1, "col": int(values["column"]) - 1, "direction": values["value"]}
    elif layout == "merge_fields":
        expected = {"fields": [field.strip() for field in values["value"].split(",") if field.strip()]}
    elif layout == "control_aliases":
        expected = {"aliases": [alias.strip() for alias in values["value"].split(",") if alias.strip()]}

    # Prevent unknown formatting values from entering stored marking definitions,
    # including requests submitted outside the browser form.
    if rule_key == "font_name" and expected not in FONT_NAMES:
        raise ValueError("Select a font from the supplied list.")
    if rule_key in {"font_color", "paragraph_shading"} and str(expected if isinstance(expected, str) else expected.get("color", "")).lower() not in COLOUR_NAMES:
        raise ValueError("Select a recognised Word colour.")
    if rule_key == "page_color" and str(expected).upper() not in PAGE_COLOURS:
        raise ValueError("Select a colour from the page-colour palette.")
    if rule_key in {"paragraph_border", "page_border"}:
        if expected.get("style", "").lower() not in BORDER_STYLES:
            raise ValueError("Select a border style from the supplied list.")
        if expected.get("color", "").lower() not in COLOUR_NAMES:
            raise ValueError("Select a recognised Word border colour.")
    if rule_key == "image_border" and expected.get("color", "").lower() not in COLOUR_NAMES:
        raise ValueError("Select a recognised Word picture-border colour.")
    if rule_key == "section_break" and str(expected) not in SECTION_BREAK_TYPES:
        raise ValueError("Select a section-break type from the supplied list.")
    elif layout == "list_style":
        expected = {"type": values["list_type"], "level": int(values["list_level"])}
    elif rule_key == "page_break":
        expected = {"count": int(values["value"])}

    if layout not in {"boolean", "margins", "page_border"} and not str(expected).strip():
        raise ValueError(f"Criterion {index + 1} needs an expected value.")

    return {
        "question_number": str(index + 1),
        "description": description,
        "domain": definition["domain"],
        "type": definition["check_type"],
        "target": target,
        "expected": expected,
        "marks": marks,
    }


def register_custom_word_task_routes(app):
    @app.route("/marking_setups/<int:setup_id>/test", methods=["GET", "POST"])
    def test_marking_setup(setup_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in {"teacher", "admin"}:
            return "Access denied", 403

        marking_conn = get_marking_db()
        try:
            setup = marking_conn.execute("SELECT title FROM marking_setups WHERE id = ?", (setup_id,)).fetchone()
        finally:
            marking_conn.close()
        if not setup:
            return "Marking setup not found", 404

        error = None
        result = None
        if request.method == "POST":
            sample = request.files.get("sample_submission")
            if not sample or not sample.filename:
                error = "Choose a completed Word document to test."
            elif not sample.filename.lower().endswith(".docx"):
                error = "The test submission must be a .docx file."
            else:
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as handle:
                        sample.save(handle)
                        temp_path = handle.name
                    result = mark_with_setup(temp_path, setup_id)
                    if result.get("error"):
                        error = result["error"]
                finally:
                    if temp_path:
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass

        return render_template("test_marking_setup.html", setup_id=setup_id, setup_title=setup[0], error=error, result=result)

    @app.route("/subjects/<int:subject_id>/custom_word_task", methods=["GET", "POST"])
    def custom_word_task(subject_id):
        username = session.get("username")
        if not username:
            return redirect(url_for("login"))
        if get_user_role(username) not in {"teacher", "admin"}:
            return "Access denied", 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,))
        subject = cursor.fetchone()
        groups = [row[0] for row in cursor.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")]
        conn.close()
        if not subject:
            return "Subject not found", 404

        error = None
        if request.method == "POST":
            try:
                title = request.form.get("title", "").strip()
                instructions = request.form.get("instructions", "").strip()
                starter = request.files.get("starter_file")
                paper = request.files.get("question_paper")
                reference_image = request.files.get("reference_image")
                if not title or not starter or not starter.filename:
                    raise ValueError("Task name and Word starter document are required.")
                if not starter.filename.lower().endswith(".docx"):
                    raise ValueError("The Word starter document must be a .docx file.")
                starter_blob = starter.read()
                starter_name = secure_filename(starter.filename)

                rules = []
                for index in range(int(request.form.get("criterion_count", "0") or 0)):
                    rule = _rule_from_form(index)
                    if rule:
                        rules.append(rule)
                if not rules:
                    raise ValueError("Add at least one marking criterion.")
                if any(rule["type"] == "image_matches_reference" for rule in rules):
                    if not reference_image or not reference_image.filename:
                        raise ValueError("Upload the reference image for the picture-match criterion.")
                    reference_hash = hashlib.sha256(reference_image.read()).hexdigest()
                    for rule in rules:
                        if rule["type"] == "image_matches_reference":
                            rule["expected"] = {"sha256": reference_hash}

                now = datetime.now().isoformat()
                setup = {"task_name": title, "program": "word", "file": "student_file.docx", "questions": rules, "total_marks": sum(rule["marks"] for rule in rules)}
                paper_blob = paper.read() if paper and paper.filename else None
                paper_name = secure_filename(paper.filename) if paper and paper.filename else None
                marking_conn = get_marking_db()
                try:
                    marking_cursor = marking_conn.cursor()
                    marking_cursor.execute(
                        """INSERT INTO marking_setups (title, created_by, created_at, updated_at, question_paper_filename, question_paper_blob, json_script_filename, json_script_blob, notes, starter_file_filename, starter_file_blob)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (title, username, now, now, paper_name, paper_blob,
                         f"{secure_filename(title)}.json", json.dumps(setup, ensure_ascii=False).encode("utf-8"), instructions, starter_name, starter_blob),
                    )
                    setup_id = marking_cursor.lastrowid
                    marking_conn.commit()
                finally:
                    marking_conn.close()

                conn = get_db()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        """INSERT INTO tasks (subject_id, name, assign_date, created_by, created_at, marking_script, marking_setup_id, task_type, is_active, sample_file, sample_file_name, allow_multiple, max_attempts, question_text, practical_mode)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 'practical', ?, ?, ?, 0, 1, ?, 'upload')""",
                        (subject_id, title, request.form.get("assign_date"), username, now, "marking_experiment_adapter", setup_id,
                         1 if request.form.get("is_active") else 0, starter_blob, starter_name, instructions),
                    )
                    task_id = cursor.lastrowid
                    for group in request.form.getlist("groups"):
                        cursor.execute("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", (task_id, group))
                    for teacher in request.form.getlist("teachers"):
                        cursor.execute("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", (task_id, teacher))
                    if paper_blob and paper_name:
                        cursor.execute("INSERT INTO task_resources (task_id, file_name, file_blob, created_at) VALUES (?, ?, ?, ?)", (task_id, paper_name, paper_blob, now))
                    for support in request.files.getlist("support_files"):
                        if support and support.filename:
                            cursor.execute("INSERT INTO task_resources (task_id, file_name, file_blob, created_at) VALUES (?, ?, ?, ?)", (task_id, secure_filename(support.filename), support.read(), now))
                    conn.commit()
                finally:
                    conn.close()
                log_activity(username, f"created no-code Word practical task {title}")
                return redirect(url_for("manage_tasks", subject_id=subject_id))
            except Exception as exc:
                error = str(exc)

        return render_template(
            "custom_word_task.html",
            subject_id=subject_id,
            subject_name=subject[0],
            groups=groups,
            teachers=get_teachers(),
            rules=RULES,
            font_names=FONT_NAMES,
            colour_names=COLOUR_NAMES,
            border_styles=BORDER_STYLES,
            page_colours=PAGE_COLOURS,
            section_break_types=SECTION_BREAK_TYPES,
            username=username,
            today=datetime.now().date().isoformat(),
            error=error,
        )
