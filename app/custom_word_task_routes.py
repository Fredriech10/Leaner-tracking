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
COLOUR_NAMES = (
    "black", "white", "grey", "light grey", "dark grey",
    "blue", "light blue", "dark blue", "green", "light green", "dark green",
    "red", "dark red", "orange", "yellow", "purple",
)
BORDER_STYLES = ("single", "double", "dotted", "dashed", "thick", "triple", "wave")
PAGE_COLOURS = ("FFFFFF", "000000", "0000FF", "0070C0", "00B050", "C6E0B4", "FF0000", "FFFF00", "D9D9D9")
SECTION_BREAK_TYPES = ("nextPage", "continuous", "evenPage", "oddPage")
PAGE_NUMBER_TEMPLATES = (
    "plain_number_1", "plain_number_2", "plain_number_3",
    "page_x_left", "page_x_center", "page_x_right",
    "page_x_of_y_left", "page_x_of_y_center", "page_x_of_y_right",
)


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
    "shadow": {"group": "Font", "label": "Text shadow", "domain": "font", "check_type": "shadow", "target": "text", "layout": "boolean"},
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
    "drop_cap": {"group": "Paragraph", "label": "Drop cap applied", "domain": "paragraph_formatting", "check_type": "drop_cap", "target": "text", "layout": "drop_cap_applied"},
    "drop_cap_position": {"group": "Paragraph", "label": "Drop cap position", "domain": "paragraph_formatting", "check_type": "drop_cap", "target": "text", "layout": "drop_cap_position"},
    "drop_cap_lines": {"group": "Paragraph", "label": "Drop cap lines to drop", "domain": "paragraph_formatting", "check_type": "drop_cap", "target": "text", "layout": "drop_cap_lines"},
    "paper_size": {"group": "Page layout", "label": "Paper size", "domain": "document", "check_type": "paper_size", "target": "none", "layout": "paper_size"},
    "orientation": {"group": "Page layout", "label": "Page orientation", "domain": "document", "check_type": "orientation", "target": "none", "layout": "orientation"},
    "margins": {"group": "Page layout", "label": "Custom margins", "domain": "document", "check_type": "margins", "target": "none", "layout": "margins"},
    "margin_side": {"group": "Page layout", "label": "Individual page margin", "domain": "document", "check_type": "margin_side", "target": "none", "layout": "margin_side"},
    "page_border": {"group": "Page layout", "label": "Page border", "domain": "document", "check_type": "page_border", "target": "none", "layout": "page_border"},
    "page_color": {"group": "Page layout", "label": "Page colour", "domain": "document", "check_type": "page_color", "target": "none", "layout": "value", "value_label": "Colour", "placeholder": "e.g. FFFF00"},
    "page_background": {"group": "Page layout", "label": "Page background present", "domain": "document", "check_type": "page_background_present", "target": "none", "layout": "boolean"},
    "cover_page": {"group": "Page layout", "label": "Cover page fields", "domain": "document", "check_type": "cover_page_fields", "target": "none", "layout": "cover_page"},
    "cover_page_controls": {"group": "Page layout", "label": "Completed cover-page controls", "domain": "document", "check_type": "no_empty_content_controls", "target": "none", "layout": "boolean"},
    "cover_page_control_layout": {"group": "Page layout", "label": "Cover-page title and author controls", "domain": "document", "check_type": "cover_page_controls", "target": "none", "layout": "control_aliases"},
    "cover_fill": {"group": "Page layout", "label": "Cover-page shape fill colour", "domain": "document", "check_type": "cover_fill_colour", "target": "none", "layout": "value", "value_label": "Fill colour", "placeholder": "e.g. white or FFFFFF"},
    "content_control_absent": {"group": "Page layout", "label": "Cover-page control removed", "domain": "document", "check_type": "content_control_absent", "target": "none", "layout": "value", "value_label": "Control name", "placeholder": "e.g. Subtitle"},
    "page_break": {"group": "Page layout", "label": "Page breaks", "domain": "document", "check_type": "page_break", "target": "none", "layout": "number", "value_label": "Number of page breaks", "placeholder": "e.g. 1"},
    "section_break": {"group": "Page layout", "label": "Section break", "domain": "document", "check_type": "section_page_break_type", "target": "none", "layout": "value", "value_label": "Break type", "placeholder": "e.g. nextPage or continuous"},
    "columns": {"group": "Page layout", "label": "Document columns", "domain": "document", "check_type": "columns", "target": "none", "layout": "columns"},
    "column_spacing": {"group": "Page layout", "label": "Spacing between document columns", "domain": "document", "check_type": "column_spacing", "target": "none", "layout": "column_spacing"},
    "column_separator": {"group": "Page layout", "label": "Line between columns", "domain": "document", "check_type": "column_separator", "target": "none", "layout": "boolean"},
    "column_breaks": {"group": "Page layout", "label": "Column breaks", "domain": "document", "check_type": "column_breaks", "target": "none", "layout": "number", "value_label": "Minimum column breaks", "placeholder": "e.g. 3"},
    "hyphenation": {"group": "Page layout", "label": "Automatic hyphenation", "domain": "document", "check_type": "hyphenation", "target": "none", "layout": "boolean"},
    "hyphenate_caps": {"group": "Page layout", "label": "Do not hyphenate capital-letter words", "domain": "document", "check_type": "do_not_hyphenate_caps", "target": "none", "layout": "boolean"},
    "watermark": {"group": "Page layout", "label": "Text watermark", "domain": "document", "check_type": "watermark", "target": "none", "layout": "watermark"},
    "contains_date": {"group": "Page layout", "label": "Date inserted", "domain": "document", "check_type": "contains_date", "target": "none", "layout": "boolean"},
    "header_text": {"group": "Header and footer", "label": "Header text", "domain": "document", "check_type": "header_text", "target": "none", "layout": "value", "value_label": "Header must contain", "placeholder": "e.g. Name and surname"},
    "header_learner_name": {"group": "Header and footer", "label": "Learner name in header", "domain": "document", "check_type": "header_learner_name", "target": "none", "layout": "boolean"},
    "header_date_field": {"group": "Header and footer", "label": "Automatic header date", "domain": "document", "check_type": "header_date_field", "target": "none", "layout": "header_date"},
    "header_date_right": {"group": "Header and footer", "label": "Header date on right", "domain": "document", "check_type": "header_date_right", "target": "none", "layout": "boolean"},
    "header_alignment": {"group": "Header and footer", "label": "Header alignment", "domain": "document", "check_type": "header_alignment", "target": "none", "layout": "alignment"},
    "header_text_alignment": {"group": "Header and footer", "label": "Header text and alignment", "domain": "document", "check_type": "header_text_alignment", "target": "none", "layout": "header_text_alignment"},
    "footer_text": {"group": "Header and footer", "label": "Footer text", "domain": "document", "check_type": "footer_text", "target": "none", "layout": "value", "value_label": "Footer must contain", "placeholder": "e.g. Page X of Y"},
    "footer_alignment": {"group": "Header and footer", "label": "Footer alignment", "domain": "document", "check_type": "footer_alignment", "target": "none", "layout": "alignment"},
    "first_page_footer": {"group": "Header and footer", "label": "Different first-page footer", "domain": "document", "check_type": "footer_differs", "target": "none", "layout": "boolean"},
    "page_number_footer": {"group": "Header and footer", "label": "Page number in footer", "domain": "document", "check_type": "page_number_in_footer", "target": "none", "layout": "boolean"},
    "page_number_header": {"group": "Header and footer", "label": "Page number in header", "domain": "document", "check_type": "page_number_in_header", "target": "none", "layout": "boolean"},
    "page_number_first_footer": {"group": "Header and footer", "label": "Page number in first-page footer", "domain": "document", "check_type": "page_number_in_first_footer", "target": "none", "layout": "boolean"},
    "page_number_template": {"group": "Header and footer", "label": "Page-number template", "domain": "document", "check_type": "page_number_template", "target": "none", "layout": "page_number_template"},
    "page_number_format": {"group": "Header and footer", "label": "Page-number number style", "domain": "document", "check_type": "page_number_format", "target": "none", "layout": "page_number_format"},
    "document_property": {"group": "Document information", "label": "Document property", "domain": "document", "check_type": "document_property", "target": "none", "layout": "document_property"},
    "document_property_changed": {"group": "Document information", "label": "Document property changed from starter value", "domain": "document", "check_type": "document_property_changed", "target": "none", "layout": "document_property_changed"},
    "comment_present": {"group": "Review", "label": "Comment inserted", "domain": "document", "check_type": "comments", "target": "none", "layout": "boolean"},
    "comment": {"group": "Review", "label": "Comment text", "domain": "document", "check_type": "comments", "target": "none", "layout": "value", "value_label": "Comment must contain", "placeholder": "e.g. Check the source"},
    "comment_on_text": {"group": "Review", "label": "Comment on specified text", "domain": "document", "check_type": "comment_on_text", "target": "none", "layout": "comment_anchor"},
    "find_replace": {"group": "Editing", "label": "Find and replace outcome", "domain": "document", "check_type": "find_replace", "target": "none", "layout": "find_replace"},
    "text_occurrence_count": {"group": "Editing", "label": "Exact whole-word count", "domain": "document", "check_type": "text_occurrence_count", "target": "none", "layout": "text_count"},
    "all_text_bold": {"group": "Editing", "label": "Every occurrence is bold", "domain": "document", "check_type": "all_text_bold", "target": "none", "layout": "value", "value_label": "Whole word", "placeholder": "e.g. guests"},
    "text_underline": {"group": "Editing", "label": "An occurrence is underlined", "domain": "document", "check_type": "text_underline", "target": "none", "layout": "value", "value_label": "Whole word", "placeholder": "e.g. guests"},
    "table_cell_text": {"group": "Tables", "label": "Table cell text", "domain": "table", "check_type": "cell_text", "target": "table", "layout": "table_cell_text"},
    "table_cell_alignment": {"group": "Tables", "label": "Table cell alignment", "domain": "table", "check_type": "cell_alignment", "target": "table", "layout": "table_cell_alignment"},
    "table_merge": {"group": "Tables", "label": "Merge table cells", "domain": "table", "check_type": "merge_horizontal", "target": "table", "layout": "table_merge"},
    "table_dimensions": {"group": "Tables", "label": "Inserted table size", "domain": "table", "check_type": "dimensions", "target": "table", "layout": "table_dimensions"},
    "table_borders": {"group": "Tables", "label": "Table borders", "domain": "table", "check_type": "borders", "target": "table", "layout": "boolean"},
    "table_border_details": {"group": "Tables", "label": "Table outside-border style", "domain": "table", "check_type": "border_details", "target": "table", "layout": "paragraph_border"},
    "table_row_shading": {"group": "Tables", "label": "Table row shading", "domain": "table", "check_type": "row_shading", "target": "table", "layout": "table_row_shading"},
    "table_row_shaded": {"group": "Tables", "label": "Table row has shading", "domain": "table", "check_type": "row_shading", "target": "table", "layout": "table_row_any_shading"},
    "table_row_height": {"group": "Tables", "label": "Table row height", "domain": "table", "check_type": "row_height", "target": "table", "layout": "table_row_height"},
    "table_row_change": {"group": "Tables", "label": "Rows added or removed from starter table", "domain": "table", "check_type": "row_count_change", "target": "table", "layout": "row_change"},
    "table_minimum_rows": {"group": "Tables", "label": "Minimum table rows", "domain": "table", "check_type": "minimum_rows", "target": "table", "layout": "number", "value_label": "Minimum rows", "placeholder": "e.g. 5"},
    "table_vertical_alignment": {"group": "Tables", "label": "Table cell vertical alignment", "domain": "table", "check_type": "cell_vertical_alignment", "target": "table", "layout": "table_vertical_alignment"},
    "table_text_direction": {"group": "Tables", "label": "Table cell text direction", "domain": "table", "check_type": "cell_text_direction", "target": "table", "layout": "table_text_direction"},
    "table_first_column_italic": {"group": "Tables", "label": "First-column data italic", "domain": "table", "check_type": "first_column_italic", "target": "table", "layout": "boolean"},
    "table_sorted_first_column": {"group": "Tables", "label": "Table sorted by first column", "domain": "table", "check_type": "sorted_first_column", "target": "table", "layout": "boolean"},
    "table_total_sum": {"group": "Tables", "label": "Final table value equals column total", "domain": "table", "check_type": "final_row_sum", "target": "table", "layout": "boolean"},
    "image_count": {"group": "Pictures and objects", "label": "Inserted picture count", "domain": "object", "check_type": "image_count", "target": "none", "layout": "number", "value_label": "Minimum pictures", "placeholder": "e.g. 1"},
    "image_width": {"group": "Pictures and objects", "label": "Picture width", "domain": "object", "check_type": "image_width", "target": "none", "layout": "number", "value_label": "Width (cm)", "placeholder": "e.g. 8"},
    "image_height": {"group": "Pictures and objects", "label": "Picture height", "domain": "object", "check_type": "image_height", "target": "none", "layout": "number", "value_label": "Height (cm)", "placeholder": "e.g. 6"},
    "image_grayscale": {"group": "Pictures and objects", "label": "Picture is grayscale", "domain": "object", "check_type": "image_grayscale", "target": "none", "layout": "boolean"},
    "image_reflection": {"group": "Pictures and objects", "label": "Picture reflection effect", "domain": "object", "check_type": "image_reflection", "target": "none", "layout": "boolean"},
    "image_alt_text": {"group": "Pictures and objects", "label": "Picture alt text", "domain": "object", "check_type": "image_alt_text", "target": "none", "layout": "value", "value_label": "Alt text must contain", "placeholder": "e.g. Tourism destination"},
    "image_alt_present": {"group": "Pictures and objects", "label": "Meaningful picture alt text", "domain": "object", "check_type": "image_alt_text", "target": "none", "layout": "boolean"},
    "image_border": {"group": "Pictures and objects", "label": "Picture border", "domain": "object", "check_type": "image_border", "target": "none", "layout": "image_border"},
    "image_caption": {"group": "Pictures and objects", "label": "Picture caption", "domain": "object", "check_type": "caption_text", "target": "none", "layout": "value", "value_label": "Caption must contain", "placeholder": "e.g. Figure 1: Tourism"},
    "image_caption_present": {"group": "Pictures and objects", "label": "Descriptive picture caption", "domain": "object", "check_type": "caption_present", "target": "none", "layout": "boolean"},
    "image_crop_applied": {"group": "Pictures and objects", "label": "Picture cropped", "domain": "object", "check_type": "image_crop", "target": "none", "layout": "boolean"},
    "image_picture_style": {"group": "Pictures and objects", "label": "Picture style applied", "domain": "object", "check_type": "image_style", "target": "none", "layout": "boolean"},
    "image_tight_wrap": {"group": "Pictures and objects", "label": "Picture text wrap: Tight", "domain": "object", "check_type": "image_wrap_tight", "target": "none", "layout": "boolean"},
    "image_fits_layout": {"group": "Pictures and objects", "label": "Picture fits page layout", "domain": "object", "check_type": "image_fits_layout", "target": "none", "layout": "boolean"},
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
    "list_after_heading": {"group": "Lists", "label": "Bulleted list below heading", "domain": "list", "check_type": "list_after_heading", "target": "none", "layout": "list_after_heading"},
    "list_symbol_after_heading": {"group": "Lists", "label": "List symbol below heading", "domain": "list", "check_type": "list_symbol_after_heading", "target": "none", "layout": "list_symbol_after_heading"},
    "bookmark": {"group": "References", "label": "Bookmark", "domain": "advanced", "check_type": "bookmark", "target": "none", "layout": "value", "value_label": "Bookmark name", "placeholder": "e.g. Introduction"},
    "bibliography": {"group": "References", "label": "Sources / bibliography", "domain": "advanced", "check_type": "bibliography", "target": "none", "layout": "number", "value_label": "Minimum sources", "placeholder": "e.g. 2"},
    "footnote": {"group": "References", "label": "Footnote text", "domain": "document", "check_type": "footnote_text", "target": "none", "layout": "value", "value_label": "Footnote must contain", "placeholder": "e.g. Source: Statistics SA"},
    "footnote_on_text": {"group": "References", "label": "Footnote attached to text", "domain": "document", "check_type": "footnote_on_text", "target": "none", "layout": "value", "value_label": "Text with footnote", "placeholder": "e.g. mobile marketing"},
    "footnote_reference_symbol": {"group": "References", "label": "Footnote reference-mark symbol", "domain": "document", "check_type": "footnote_reference_symbol", "target": "none", "layout": "footnote_symbol"},
    "table_of_contents": {"group": "References", "label": "Automatic table of contents", "domain": "document", "check_type": "table_of_contents", "target": "none", "layout": "boolean"},
    "toc_before_heading": {"group": "References", "label": "Table of contents before heading", "domain": "document", "check_type": "toc_before_heading", "target": "none", "layout": "value", "value_label": "Heading below the contents", "placeholder": "e.g. Introduction"},
    "toc_levels": {"group": "References", "label": "Table-of-contents levels", "domain": "document", "check_type": "toc_levels", "target": "none", "layout": "number", "value_label": "Levels to show", "placeholder": "e.g. 2"},
    "toc_formal": {"group": "References", "label": "Formal table-of-contents style", "domain": "document", "check_type": "toc_formal", "target": "none", "layout": "boolean"},
    "heading_style": {"group": "Styles", "label": "Heading or paragraph style", "domain": "advanced", "check_type": "style_applied", "target": "text", "layout": "style"},
    "style_font_name": {"group": "Styles", "label": "Style font name", "domain": "advanced", "check_type": "style_font_name", "target": "none", "layout": "style_font_name"},
    "style_underline": {"group": "Styles", "label": "Style underline", "domain": "advanced", "check_type": "style_underline", "target": "none", "layout": "style_boolean"},
    "style_shadow": {"group": "Styles", "label": "Style text shadow", "domain": "advanced", "check_type": "style_shadow", "target": "none", "layout": "style_boolean"},
    "style_underline_type": {"group": "Styles", "label": "Style underline type", "domain": "advanced", "check_type": "style_underline_type", "target": "none", "layout": "style_underline_type"},
    "style_character_spacing": {"group": "Styles", "label": "Style character spacing", "domain": "advanced", "check_type": "style_character_spacing", "target": "none", "layout": "style_number"},
    "paragraph_after_heading_style": {"group": "Styles", "label": "Paragraph below heading uses style", "domain": "advanced", "check_type": "paragraph_after_heading_style", "target": "none", "layout": "heading_followed_style"},
    "heading_style_count": {"group": "Styles", "label": "Minimum headings with a style", "domain": "advanced", "check_type": "style_count", "target": "none", "layout": "style_count"},
    "heading_numbering": {"group": "Styles", "label": "Heading numbering format", "domain": "document", "check_type": "heading_number_format", "target": "text", "layout": "number_format"},
    "mail_merge_fields": {"group": "Mail merge", "label": "Mail merge fields", "domain": "document", "check_type": "mail_merge_fields", "target": "none", "layout": "merge_fields"},
    "mail_merge_source": {"group": "Mail merge", "label": "Mail merge data source", "domain": "document", "check_type": "mail_merge_source", "target": "none", "layout": "value", "value_label": "Data source filename", "placeholder": "e.g. Client List.xlsx"},
    "hyperlink_present": {"group": "References", "label": "Hyperlink inserted", "domain": "object", "check_type": "hyperlink_present", "target": "none", "layout": "boolean"},
    "hyperlink_url": {"group": "References", "label": "Hyperlink destination", "domain": "object", "check_type": "hyperlink_url", "target": "none", "layout": "value", "value_label": "Destination must contain", "placeholder": "e.g. wikipedia.org or 1Bio_Data.docx"},
    "hyperlink_text": {"group": "References", "label": "Hyperlink display text", "domain": "object", "check_type": "hyperlink_text", "target": "none", "layout": "value", "value_label": "Link text must contain", "placeholder": "e.g. Visit the website"},
    "hyperlink_text_destination": {"group": "References", "label": "Hyperlink text and destination", "domain": "object", "check_type": "hyperlink_text_destination", "target": "none", "layout": "hyperlink_text_destination"},
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
        "value", "value_2", "value_3", "row", "column", "column_end", "top", "bottom", "left", "right", "line_rule", "line_unit", "list_type", "list_level", "tolerance", "target_mode", "side"
    )}
    # Each selected action is one mark. Baseline text marks are added separately.
    marks = 1
    if not description or rule_key not in RULES:
        return None

    definition = RULES[rule_key]
    is_paragraph_rule = definition["domain"] == "paragraph_formatting"
    target_mode = values["target_mode"] or "contains_text"
    if (definition["target"] == "text" or is_paragraph_rule) and not target_text and target_mode != "any_drop_cap":
        raise ValueError(f"Criterion {index + 1} needs target text to locate the change.")

    target = {}
    if is_paragraph_rule:
        if target_mode not in {"contains_text", "after_heading", "any_drop_cap"}:
            raise ValueError("Select how the paragraph should be located.")
        target = {"locator": target_mode, "value": target_text}
    elif definition["target"] == "text":
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
    elif layout == "margin_side":
        expected = {"side": values["side"], "value": float(values["value"])}
    elif layout == "style_count":
        expected = {"style": values["value"], "minimum": int(values["value_2"]), "texts": [text.strip() for text in values["value_3"].split(",") if text.strip()]}
    elif layout == "style_font_name":
        expected = {"style": values["value"], "font": values["value_2"]}
    elif layout == "style_boolean":
        expected = {"style": values["value"], "value": values["value_2"].lower() not in {"false", "no", "0"}}
    elif layout == "text_count":
        expected = {"text": values["value"], "count": int(values["value_2"])}
    elif layout == "style_underline_type":
        expected = {"style": values["value"], "underline": values["value_2"]}
    elif layout == "style_number":
        expected = {"style": values["value"], "value": float(values["value_2"])}
    elif layout == "heading_followed_style":
        expected = {"heading": values["value"], "style": values["value_2"]}
    elif layout == "comment_anchor":
        expected = {"text": values["value"], "comment": values["value_2"]}
    elif layout == "hyperlink_text_destination":
        expected = {"text": values["value"], "destination": values["value_2"]}
    elif layout == "page_border":
        expected = {"style": values["value"], "color": values["value_2"], "first_page_only": values["value_3"].lower() in {"true", "yes", "1"}}
    elif layout == "watermark":
        expected = {"text": values["value"], "color": values["value_2"], "layout": values["value_3"]}
    elif layout == "header_text_alignment":
        expected = {"text": values["value"], "alignment": values["value_2"]}
    elif layout == "header_date":
        expected = {"format": values["value"], "automatic": values["value_2"].lower() not in {"false", "no", "0"}}
    elif layout == "page_number_template":
        expected = {"template": values["value"], "location": values["value_2"] or "footer"}
    elif layout == "drop_cap_applied":
        expected = {"applied": values["value"].lower() not in {"false", "no", "0"}}
    elif layout == "drop_cap_position":
        expected = {"position": values["value"]}
    elif layout == "drop_cap_lines":
        expected = {"lines": int(values["value"])}
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
    elif layout == "table_row_any_shading":
        expected = {"row": int(values["row"]) - 1, "color": "any"}
    elif layout == "image_border":
        expected = {"width_pt": float(values["value"]), "color": values["value_2"]}
    elif layout == "document_property":
        expected = {"property": values["value"], "value": values["value_2"]}
    elif layout == "document_property_changed":
        expected = {"property": values["value"], "starter_value": values["value_2"]}
    elif layout == "cover_page":
        expected = {name: values[name] for name in ("value", "value_2", "value_3")}
        expected = {"title": expected["value"], "author": expected["value_2"], "abstract": expected["value_3"]}
    elif layout == "columns":
        expected = {"count": int(values["value"])}
        if values["value_2"]:
            expected["space_cm"] = float(values["value_2"])
    elif layout == "column_spacing":
        expected = {"count": int(values["value"]), "space_cm": float(values["value_2"])}
    elif layout == "find_replace":
        expected = {"find": values["value"], "replace": values["value_2"], "minimum_replacements": int(values["value_3"])}
    elif layout == "table_row_height":
        expected = {"row": int(values["row"]) - 1, "height_cm": float(values["value"])}
    elif layout == "row_change":
        expected = {"delta": int(values["value"])}
    elif layout == "footnote_symbol":
        expected = {"text": values["value"], "font": values["value_2"], "character_code": values["value_3"]}
    elif layout == "list_after_heading":
        expected = {"heading": values["value"], "minimum": int(values["value_2"])}
    elif layout == "list_symbol_after_heading":
        expected = {"heading": values["value"], "font": values["value_2"], "character_code": values["value_3"]}
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
        if expected.get("color") and expected.get("color", "").lower() not in COLOUR_NAMES:
            raise ValueError("Select a recognised Word border colour.")
    if rule_key == "image_border" and expected.get("color", "").lower() not in COLOUR_NAMES:
        raise ValueError("Select a recognised Word picture-border colour.")
    if rule_key == "section_break" and str(expected) not in SECTION_BREAK_TYPES:
        raise ValueError("Select a section-break type from the supplied list.")
    if rule_key == "page_number_template" and expected.get("template") not in PAGE_NUMBER_TEMPLATES:
        raise ValueError("Select a page-number template from the supplied list.")
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
        "builder_rule": rule_key,
        "builder_values": values,
        "builder_target": target_text,
    }


def _add_automatic_text_marks(rules):
    """Award one baseline mark for each distinct text target before its formatting checks."""
    manually_marked = {
        " ".join(str(rule.get("expected", "")).lower().split())
        for rule in rules
        if rule.get("type") == "contains_text"
    }
    added_targets = set()
    expanded = []
    for rule in rules:
        target = rule.get("target") or {}
        target_text = str(target.get("value", "")).strip() if target.get("locator") == "contains_text" else ""
        normalized_target = " ".join(target_text.lower().split())
        if target_text and normalized_target not in manually_marked and normalized_target not in added_targets:
            expanded.append({
                "description": f"Correct text: {target_text}",
                "domain": "document",
                "type": "contains_text",
                "target": {},
                "expected": target_text,
                "marks": 1,
            })
            added_targets.add(normalized_target)
        expanded.append(rule)

    for number, rule in enumerate(expanded, start=1):
        rule["question_number"] = str(number)
    return expanded


def _expand_composite_rules(rules):
    """Turn compound builder actions into the one-mark rows shown in a memo."""
    expanded = []
    for rule in rules:
        expected = rule["expected"]
        description = rule["description"]
        if rule["type"] == "margins" and isinstance(expected, dict):
            expanded.extend((
                {**rule, "description": f"{description}: top and bottom margins", "type": "margin_top_bottom_cm", "expected": expected["top"]},
                {**rule, "description": f"{description}: left and right margins", "type": "margin_left_right_cm", "expected": expected["left"]},
            ))
        elif rule["type"] == "page_border" and isinstance(expected, dict):
            expanded.append({**rule, "description": f"{description}: border applied", "expected": {}})
            expanded.append({**rule, "description": f"{description}: {expected['style']} border style", "expected": {"style": expected["style"]}})
            expanded.append({**rule, "description": f"{description}: first-page setting", "expected": {"first_page_only": expected["first_page_only"]}})
            if expected.get("color"):
                expanded.append({**rule, "description": f"{description}: {expected['color']} border colour", "expected": {"color": expected["color"]}})
        elif rule["type"] == "watermark" and isinstance(expected, dict):
            for key, label in (("text", "watermark text"), ("color", "watermark colour"), ("layout", "watermark layout")):
                if expected.get(key):
                    expanded.append({**rule, "description": f"{description}: {label}", "expected": expected[key]})
        elif rule["type"] == "page_number_template" and isinstance(expected, dict):
            template = expected["template"]
            location = expected.get("location", "footer")
            alignment = template.rsplit("_", 1)[-1] if template.startswith(("page_x_", "page_x_of_y_")) else {"plain_number_1": "left", "plain_number_2": "center", "plain_number_3": "right"}[template]
            structure = "page_x_of_y" if template.startswith("page_x_of_y_") else "page_x" if template.startswith("page_x_") else "plain_number"
            expanded.extend((
                {**rule, "description": f"{description}: automatic page-number field", "type": f"page_number_in_{location}", "expected": True},
                {**rule, "description": f"{description}: {structure.replace('_', ' ').title()} format", "expected": {"template": structure, "location": location}},
                {**rule, "description": f"{description}: {alignment} alignment", "type": f"{location}_alignment", "expected": alignment},
            ))
        else:
            expanded.append(rule)
    return expanded


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

    @app.route("/tasks/<int:task_id>/word_builder/edit", methods=["GET", "POST"])
    def edit_custom_word_task(task_id):
        username = session.get("username")
        if not username or get_user_role(username) not in {"teacher", "admin"}:
            return "Access denied", 403

        conn = get_db()
        task = conn.execute(
            "SELECT subject_id, name, assign_date, question_text, is_active, marking_setup_id FROM tasks WHERE id = ? AND task_type = 'practical'",
            (task_id,),
        ).fetchone()
        if not task or not task[5]:
            conn.close()
            return "This task does not have a no-code Word marking setup.", 404
        subject_id, task_name, assign_date, instructions, is_active, setup_id = task
        subject = conn.execute("SELECT name FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        groups = [row[0] for row in conn.execute("SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name")]

        marking_conn = get_marking_db()
        setup_row = marking_conn.execute("SELECT json_script_blob FROM marking_setups WHERE id = ?", (setup_id,)).fetchone()
        if not setup_row:
            marking_conn.close()
            conn.close()
            return "Marking setup not found", 404
        setup = json.loads((setup_row[0] or b"{}").decode("utf-8"))
        initial_criteria = setup.get("builder_criteria") or []
        if not initial_criteria:
            marking_conn.close()
            conn.close()
            return "This older task can be edited in Marking Setup, but it was created before no-code builder data was saved.", 400

        error = None
        if request.method == "POST":
            try:
                builder_rules = [rule for index in range(int(request.form.get("criterion_count", "0") or 0)) if (rule := _rule_from_form(index))]
                if not builder_rules:
                    raise ValueError("Add at least one marking criterion.")
                rules = _add_automatic_text_marks(_expand_composite_rules(builder_rules))
                title = request.form.get("title", "").strip()
                if not title:
                    raise ValueError("Task name is required.")
                setup.update({"task_name": title, "questions": rules, "builder_criteria": builder_rules, "total_marks": sum(rule["marks"] for rule in rules)})
                marking_conn.execute("UPDATE marking_setups SET title = ?, notes = ?, json_script_blob = ?, updated_at = ? WHERE id = ?", (title, request.form.get("instructions", ""), json.dumps(setup, ensure_ascii=False).encode("utf-8"), datetime.now().isoformat(), setup_id))
                marking_conn.commit()
                conn.execute("UPDATE tasks SET name = ?, assign_date = ?, question_text = ?, is_active = ? WHERE id = ?", (title, request.form.get("assign_date"), request.form.get("instructions", ""), 1 if request.form.get("is_active") else 0, task_id))
                conn.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))
                conn.executemany("INSERT INTO task_groups (task_id, group_name) VALUES (?, ?)", [(task_id, group) for group in request.form.getlist("groups")])
                conn.execute("DELETE FROM task_teachers WHERE task_id = ?", (task_id,))
                conn.executemany("INSERT INTO task_teachers (task_id, teacher_username) VALUES (?, ?)", [(task_id, teacher) for teacher in request.form.getlist("teachers")])
                conn.commit()
                log_activity(username, f"edited no-code Word practical task {title}")
                return redirect(url_for("manage_tasks", subject_id=subject_id))
            except Exception as exc:
                error = str(exc)
        marking_conn.close()
        conn.close()
        return render_template("custom_word_task.html", subject_id=subject_id, subject_name=subject[0], groups=groups, teachers=get_teachers(), rules=RULES, font_names=FONT_NAMES, colour_names=COLOUR_NAMES, border_styles=BORDER_STYLES, page_colours=PAGE_COLOURS, section_break_types=SECTION_BREAK_TYPES, username=username, today=datetime.now().date().isoformat(), error=error, editing_task={"name": task_name, "assign_date": assign_date, "instructions": instructions, "is_active": is_active}, initial_criteria=initial_criteria)

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

                builder_rules = []
                for index in range(int(request.form.get("criterion_count", "0") or 0)):
                    rule = _rule_from_form(index)
                    if rule:
                        builder_rules.append(rule)
                if not builder_rules:
                    raise ValueError("Add at least one marking criterion.")
                rules = _add_automatic_text_marks(_expand_composite_rules(builder_rules))
                if any(rule["type"] == "image_matches_reference" for rule in rules):
                    if not reference_image or not reference_image.filename:
                        raise ValueError("Upload the reference image for the picture-match criterion.")
                    reference_hash = hashlib.sha256(reference_image.read()).hexdigest()
                    for rule in rules:
                        if rule["type"] == "image_matches_reference":
                            rule["expected"] = {"sha256": reference_hash}

                now = datetime.now().isoformat()
                setup = {
                    "task_name": title,
                    "program": "word",
                    "file": "student_file.docx",
                    "questions": rules,
                    "builder_criteria": builder_rules,
                    "total_marks": sum(rule["marks"] for rule in rules),
                }
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
            editing_task=None,
            initial_criteria=[],
        )
