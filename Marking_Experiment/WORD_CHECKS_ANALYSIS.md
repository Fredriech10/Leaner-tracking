# Word Document Checks Comprehensive Analysis

## Overview
This document analyzes the current Word document checking capabilities in the Marking Experiment and identifies gaps in coverage for a complete Word formatting/content validation system.

### Recent progress
- Tier 1 infrastructure for deterministic Word marking was added in May 2026.
- New support modules: `utils.py`, `targeting.py`, `task_validator.py`, `config.py`.
- Numeric comparisons now use centralized unit conversion and tolerance logic.
- Paragraph/table targeting now uses fallbacks and fuzzy matching instead of brittle fixed-index logic.
- Validation and logging were improved, and `Marking_Experiment/test_tier1_improvements.py` passes.

---

## CURRENTLY IMPLEMENTED CHECKS

### 1. Document-Level Checks (`checks/document.py`)
✓ `page_count` - Estimates pages from character count
✓ `word_count` - Counts words
✓ `character_count` - Counts characters
✓ `paragraph_count` - Counts paragraphs
✓ `has_headers` - Checks header presence
✓ `has_footers` - Checks footer presence
✓ `page_orientation` - Portrait/landscape
✓ `page_size` - Page dimensions (A4, Letter, etc.)
✓ `margins` - Top, bottom, left, right margins
✓ `contains_text` - Document-wide text search
✓ `language` - Document language (placeholder)

### 2. Document/Page Setup Checks (`word_checker.py`)
✓ `paper_size` - Paper size matching for standard page dimensions
✓ `orientation` - Portrait/landscape orientation
✓ `margins` - Section margin values
✓ `page_border` - Page border style detection
✓ `watermark` - Watermark presence/text/color/layout detection
✓ `header_text` - Header text presence or match
✓ `header_alignment` - Header paragraph alignment
✓ `footer_text` - Footer text presence or match
✓ `footer_alignment` - Footer alignment
✓ `header_content` - Header text verification
✓ `footer_content` - Footer text verification
✓ `header_differs` - Different first page header
✓ `footer_differs` - Different first page footer
✓ `page_number_in_header` - Page numbers in headers
✓ `page_number_in_footer` - Page numbers in footers
✓ `page_number_format` - Number format (1, i, I, a, A)
✓ `page_break` - Page break presence/count
✓ `section_page_break_type` - Section break type (continuous, odd, even, next page)
✓ `line_numbers` - Line numbering settings
✓ `gutter_margin` - Gutter margin
✓ `mirror_margins` - Mirror margins setting
✓ `page_color` - Page background color
✓ `hyphenation` - Document hyphenation enabled/disabled
✓ `contains_date` - Document contains a date pattern

### 3. Paragraph Formatting Checks (`word_checker.py`)
✓ `alignment` - Left, center, right, justify
✓ `line_spacing` - Points or line spacing rules with tolerance logic
✓ `space_before` - Spacing before paragraph
✓ `space_after` - Spacing after paragraph
✓ `first_line_indent` - First line indentation
✓ `hanging_indent` - Hanging indentation
✓ `left_indent` - Left paragraph indentation
✓ `right_indent` - Right paragraph indentation
✓ `right_to_left` - Right-to-left paragraph direction
✓ `keep_with_next` - Keep paragraph with the next paragraph
✓ `keep_lines_together` - Keep lines together within the paragraph
✓ `widow_orphan_control` - Widow/orphan control
✓ `page_break_before` - Page break before paragraph
✓ `outline_level` - Outline level setting
✓ `tabs` - Tab stop position and alignment
✓ `contains_text` - Text search in paragraph target
✓ `border` - Paragraph borders
✓ `shading` - Paragraph background fill
✓ `drop_cap` - Drop cap formatting

### 4. Font Checks (`word_checker.py`)
✓ `color` - Font color (RGB + theme colors)
✓ `size` - Font size in points with tolerance
✓ `bold` - Bold formatting
✓ `italic` - Italic formatting
✓ `bold_and_color` - Combined bold + color
✓ `underline` - Underline formatting
✓ `strikethrough` - Strikethrough formatting
✓ `double_strikethrough` - Double strikethrough detection
✓ `all_caps` - All caps text
✓ `small_caps` - Small capitals text
✓ `subscript` - Subscript text
✓ `superscript` - Superscript text
✓ `shadow` - Shadow text effect
✓ `outline` - Outline text effect
✓ `emboss` - Emboss text effect
✓ `hidden` - Hidden text formatting
✓ `font_name` - Font family name
✓ `font_theme` - Theme font reference
✓ `character_spacing` - Character spacing metadata
✓ `kerning` - Kerning metadata

### 5. Table Checks (`word_checker.py`)
✓ `merge_horizontal` - Horizontal merge span
✓ `cell_text` - Cell text content matching
✓ `cell_alignment` - Table cell alignment

### 6. List Checks (`word_checker.py`)
✓ `list_style` - List style detection
✓ `bullet_char` - Bullet character detection
✓ `indent_level` - List indentation level
✓ `list_paragraph_font` - Font checks inside list paragraphs

### 7. Object Checks (`word_checker.py`)
✓ `image_width` - Image width detection from Word XML
✓ `image_border` - Image border width/color
✓ `image_crop` - Image crop/shape detection
✓ `smartart` - SmartArt presence and optional type match
✓ `smartart_text` - SmartArt contained text
✓ `smartart_color` - SmartArt color scheme

### 8. Advanced Checks (`word_checker.py`)
✓ `style_applied` - Named style detection on paragraphs
✓ `bookmark` - Bookmark presence by name
✓ `bibliography` - Bibliography/source count presence

---

## CRITICAL GAPS - MISSING CHECKS

### Font/Character Formatting
- ❌ `word_spacing` - Spacing between words

### Paragraph Advanced Formatting
✓ `hanging_indent` - Hanging indentation
✓ `left_indent` - Left paragraph indentation
✓ `right_indent` - Right paragraph indentation
✓ `right_to_left` - RTL paragraph direction
✓ `keep_with_next` - Keep paragraph with next
✓ `keep_lines_together` - Keep lines together
✓ `widow_orphan_control` - Widow/orphan control
✓ `page_break_before` - Page break before paragraph
✓ `outline_level` - Outline level setting
✓ `tabs` - Tab stops (position, type, leader)

### Hyperlinks & Cross-References
- ❌ `hyperlink_url` - Verify hyperlink destinations
- ❌ `hyperlink_text` - Hyperlink display text
- ❌ `cross_reference` - Cross-reference presence
- ❌ `cross_reference_target` - Cross-ref target validation

### Image/Object Properties
- ❌ `image_rotation` - Image rotation angle
- ❌ `image_compression` - Image compression state
- ❌ `image_transparency` - Image transparency
- ❌ `image_text_wrapping` - Text wrapping around image (none, square, tight, through, topbottom)
- ❌ `image_anchor_position` - Image anchor (inline, floating, specific position)
- ❌ `image_aspect_ratio` - Image aspect ratio locked
- ❌ `image_alt_text` - Alt text for accessibility
- ❌ `shape_rotation` - Shape rotation angle
- ❌ `shape_fill_color` - Shape fill color
- ❌ `shape_outline_color` - Shape outline color
- ❌ `shape_outline_width` - Shape outline width
- ❌ `shape_shadow` - Shape shadow effect
- ❌ `shape_3d_effects` - Shape 3D effects
- ❌ `shape_text_content` - Text inside shapes
- ❌ `textbox` - Text box presence/content

### Table Advanced Formatting
- ❌ `table_cell_width` - Cell width (fixed/auto)
- ❌ `table_row_height` - Row height
- ❌ `table_cell_margin` - Cell margins
- ❌ `table_cell_vertical_align` - Cell vertical alignment (top, center, bottom)
- ❌ `table_cell_merge` - Merged cells detection
- ❌ `table_cell_border` - Individual cell borders
- ❌ `table_cell_border_color` - Cell border color
- ❌ `table_nested` - Nested table detection
- ❌ `table_style` - Table style name
- ❌ `table_repeating_header` - Header row repeat setting
- ❌ `table_banding` - Row/column banding

### Header/Footer Content
- Status: no dedicated header/footer content and numbering checks are implemented yet
- ❌ `header_content` - Header text verification
- ❌ `footer_content` - Footer text verification
- ❌ `header_differs` - Different first page header
- ❌ `footer_differs` - Different first page footer
- ❌ `page_number_in_header` - Page numbers in headers
- ❌ `page_number_in_footer` - Page numbers in footers
- ❌ `page_number_format` - Number format (1, i, I, a, A)

### Page Setup & Layout
- Status: section and layout-specific document settings remain unimplemented
- ❌ `page_break` - Page break presence/count
- ❌ `section_page_break_type` - Section break type (continuous, odd, even, next page)
- ❌ `line_numbers` - Line numbering settings
- ❌ `gutter_margin` - Gutter margin
- ❌ `mirror_margins` - Mirror margins setting
- ❌ `page_color` - Page background color

### Bibliography & Sources
- ❌ `sources` - Sources/citations count
- ❌ `citation_style` - Citation style name (MLA, APA, Chicago, etc.)
- ❌ `works_cited` - Works cited page presence

### Content & Styles
- ❌ `style_font_properties` - Style's font settings
- ❌ `style_paragraph_properties` - Style's paragraph settings
- ❌ `style_base_style` - Style inheritance chain
- ❌ `heading_styles_used` - Heading styles present
- ❌ `style_formatting_consistency` - Consistent style usage

### Field Codes & Dynamic Content
- ❌ `field_code_type` - Specific field type (DATE, TIME, PAGE, NUMPAGES, etc.)
- ❌ `field_update_status` - Whether field is stale
- ❌ `merge_fields` - Mail merge field presence
- ❌ `form_fields` - Form field presence
- ❌ `form_field_type` - Form field type (text, checkbox, dropdown)
- ❌ `content_control` - Content control presence
- ❌ `content_control_type` - Content control type (text, rich text, dropdown, etc.)

### Equations & Complex Objects
- ❌ `equation` - Equation presence
- ❌ `equation_type` - Equation format (OLE, native Math)
- ❌ `smartart` - SmartArt graphic presence
- ❌ `quicktable` - QuickTable presence
- ❌ `ole_object` - OLE object presence
- ❌ `embedded_file` - Embedded file presence

### Document Security & Properties
- ❌ `document_encryption` - Encryption status
- ❌ `author` - Document author
- ❌ `title` - Document title
- ❌ `subject` - Document subject
- ❌ `keywords` - Document keywords
- ❌ `created_date` - Creation date
- ❌ `modified_date` - Last modified date
- ❌ `document_statistics` - Statistics display

### Accessibility
- ❌ `alt_text` - Alt text for images/shapes
- ❌ `pdf_title` - PDF title setting
- ❌ `pdf_accessibility` - PDF accessibility metadata
- ❌ `doc_accessibility_check` - Accessibility checker results

### Theme & Formatting
- ❌ `theme_colors_used` - Theme color usage
- ❌ `theme_fonts_used` - Theme font usage
- ❌ `document_theme` - Current theme name
- ❌ `background_fill` - Document background pattern/gradient
- ❌ `background_color` - Solid background color

### List Advanced Properties
- ❌ `list_bullet_character` - Bullet character type
- ❌ `list_numbering_format` - Number format (1,i,I,a,A)
- ❌ `list_start_number` - Starting number
- ❌ `outline_list` - Multi-level outline list

### Text Boxes & Shapes
- ❌ `text_box_count` - Text box count
- ❌ `text_box_content` - Text inside text boxes
- ❌ `text_box_position` - Text box positioning
- ❌ `draw_objects` - Drawing objects count

### Revision & Change Tracking
- ❌ `revision_type` - Type of revision (insertion, deletion, change)
- ❌ `revision_author` - Revision author name
- ❌ `revision_date` - Revision date/time
- ❌ `comment_author` - Comment author
- ❌ `comment_date` - Comment date/time

---

## PARTIALLY IMPLEMENTED OR PROBLEMATIC

### Already Flagged Issues
1. **Font Size (font.py:43)** - Previously used exact equality instead of tolerance.
   - Status: FIXED: now uses `compare_numeric(float(actual), float(expected), tolerance=TOLERANCE_PT, unit="pt")`.

2. **Paragraph Alignment Fallback** - Previously searched all paragraphs too aggressively.
   - Status: FIXED: targeting now resolves paragraphs with hierarchical fallback and fuzzy matching.

3. **Line Spacing Fallback** - Previously could match the first paragraph with spacing anywhere.
   - Status: FIXED: line spacing comparisons now use centralized unit conversion and tolerance logic.

4. **First Line Indent Fallback** - Previously matched the first indent anywhere.
   - Status: FIXED: indent checks now use robust paragraph location and normalized EMU→cm comparisons.

5. **Task Validation Coverage** - No Word-only enforcement previously.
   - Status: FIXED: `task_validator.py` now validates Word tasks and forces unsupported programs to `word`.

6. **Logging and Error Handling** - Silent failures were present across modules.
   - Status: Fixed: centralized logging via `config.py` and explicit warnings/errors were added.

## Summary
- Completed: Tier 1 Word marking infrastructure, numeric stability, targeting robustness, validation, and integration test coverage.
- Still missing: broad Word feature coverage in all domains (font effects, advanced paragraph/table/image checks, headers/footers, metadata, accessibility, and more).
- Current coverage remains limited to a subset of Word checks; the project still requires a prioritized roadmap for the remaining ~110+ missing Word features.


3. **Line Spacing Fallback** - Finds first paragraph with spacing anywhere
   - Status: FIXED in previous session

4. **First Line Indent Fallback** - Finds first paragraph with indent anywhere
   - Status: FIXED in previous session

5. **Hyperlink Detection (object.py)** - Only counts, doesn't validate URLs
6. **Image Size (object.py)** - Doesn't parse actual pixel dimensions
7. **Cell Formatting (table.py:91-118)** - Very basic, missing complex formatting
8. **Theme Color Handling** - Partially implemented, needs expansion
9. **List Type Detection (list.py)** - Simplified, may miss complex list styles

---

## RECOMMENDED PRIORITY TIERS

### Tier 1: HIGH PRIORITY (Most Common Use Cases)
- Font: word_spacing
- Paragraph: advanced indentation and flow checks now implemented
- Header/Footer: content validation
- Hyperlinks: URL validation
- Images: crop, rotation, text_wrapping, anchor_type
- Tables: cell borders, cell merge, row height, cell vertical alignment
- Bookmarks: bookmark presence and named ranges
- Cross-references: cross-ref validation

### Tier 2: MEDIUM PRIORITY (Common but Less Frequent)
- Character effects: word_spacing
- Content controls: detection and type validation
- Form fields: presence and type
- Page setup: page breaks, line numbers, gutter margins
- Equations: presence and basic type
- SmartArt: presence detection
- Sources: bibliography and citation detection

### Tier 3: LOWER PRIORITY (Advanced/Specialized)
- 3D effects, emboss/engrave
- Text wrapping around shapes
- Theme customization details
- Accessibility metadata
- OLE objects, embedded files
- VML shape complex properties
- Document encryption levels
- Revision tracking details

---

## IMPLEMENTATION STRATEGY

### Architecture Notes
1. Each check type should have its own module or sub-function
2. Use XML parsing (already done with lxml) for complex properties
3. Leverage python-docx API first, fallback to XML
4. Implement tolerance-based comparisons for dimensional values
5. Create utility functions to avoid code duplication

### Testing Requirements
- Unit tests for each new check type
- Integration tests with real Word documents
- Edge case testing (empty documents, complex formatting)
- Performance testing on large documents

---

## SUMMARY STATISTICS

**Currently Implemented:** ~55 check types  
**Missing/Incomplete:** ~110+ check types  
**Coverage:** ~33% of comprehensive Word formatting checks  

The system needs significant expansion to cover all Word formatting capabilities comprehensively.

## Comprehensive feedback: missing Word checks

The current checks implementation covers a limited subset of the checks in `WORD_CHECKS_ANALYSIS.md`. It is not yet comprehensive.

### 1. Document-level checks still missing
- document.py
  - `language` is only a placeholder
  - Missing metadata checks: `author`, `title`, `subject`, `keywords`, `created_date`, `modified_date`
  - Missing bibliography/source checks: `bibliography`, `sources`, `citation_style`, `works_cited`

### 2. Paragraph formatting checks still missing
- paragraph_formatting.py
  - No remaining paragraph formatting checks are currently flagged as missing in this section.

### 3. Font checks still missing
- font.py
  - `engrave`
  - `word_spacing`

### 4. Table checks still missing
- table.py
  - `table_cell_width`
  - `table_row_height`
  - `table_cell_margin`
  - `table_cell_vertical_align`
  - `table_cell_merge`
  - `table_cell_border` / `table_cell_border_color`
  - `table_nested`
  - `table_style`
  - `table_repeating_header`
  - `table_banding`

### 5. List checks still missing
- list.py
  - `list_bullet_character`
  - `list_numbering_format`
  - `list_start_number`
  - `outline_list`
  - More robust level/type detection for complex numbering styles
  - Better detection for multi-level continuation semantics

### 6. Object checks still missing
- object.py
  - `image_crop`
  - `image_rotation`
  - `image_compression`
  - `image_transparency`
  - `image_text_wrapping`
  - `image_anchor_position`
  - `image_aspect_ratio`
  - `image_alt_text`
  - `shape_rotation`
  - `shape_fill_color`
  - `shape_outline_color`
  - `shape_outline_width`
  - `shape_shadow`
  - `shape_3d_effects`
  - `shape_text_content`
  - `textbox` / `text_box_content`
  - `hyperlink_url`
  - `hyperlink_text`
  - `cross_reference`
  - `cross_reference_target`
  - `bookmarks`, `bookmark_name`, `bookmark_content`
  - `embedded_file`, `ole_object`, `smartart`, `equation`

### 7. Header/footer checks still missing
- No dedicated `header_content` / `footer_content`
- No `header_differs`, `footer_differs`
- No `page_number_in_header`, `page_number_in_footer`
- No `page_number_format`

### 8. Page setup/layout checks still missing
- No `page_break`
- No `section_page_break_type`
- No `line_numbers`
- No `gutter_margin`
- No `mirror_margins`
- No `page_color`

### 9. Advanced checks still missing
- advanced.py
  - `style_font_properties`
  - `style_paragraph_properties`
  - `style_base_style`
  - `heading_styles_used`
  - `style_formatting_consistency`
  - `field_code_type`
  - `field_update_status`
  - `merge_fields`
  - `form_fields`, `form_field_type`
  - `content_control`, `content_control_type`
  - `equation_type`
  - `smartart`
  - `quicktable`
  - `embedded_file`
  - `document_encryption`
  - `document_statistics`
  - `alt_text` accessibility checks
  - `pdf_title`, `pdf_accessibility`
  - `doc_accessibility_check`
  - `theme_colors_used`, `theme_fonts_used`, `document_theme`
  - `background_fill`, `background_color`
  - `text_box_count`
  - `draw_objects`
  - `revision_type`, `revision_author`, `revision_date`
  - `comment_author`, `comment_date`

### 9. Implementation quality gaps to address
- Some implemented checks are approximate, not exact:
  - `page_count` uses char-count estimation
  - `line_spacing`, `first_line_indent`, `alignment` use fallback scanning
  - font.py size uses exact equality instead of tolerance
  - object.py image size returns width/height only if found, but `_find_images()` does not expose actual dimensions
  - Hyperlink/footnote/endnote XML attribute access is malformed and likely unreliable

### Recommendation
If the goal is full coverage, the next step should be:
1. add missing feature checks in each domain
2. fix existing weak implementations and XML parsing bugs
3. add unit tests for each new check and edge cases

If you want, I can next produce a prioritized implementation roadmap for these missing Word checks.