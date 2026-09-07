# Word Practical Builder Coverage Audit

Source markers reviewed: Grade 10 Term 2 and Term 3, Grade 11 Term 2 and Term 3, Grade 12 Term 2, plus the standalone paragraph and page-formatting markers.

## Available In The Builder

| Marker outcome | Builder action |
| --- | --- |
| Font family, size, colour, bold, italic, underline, strike-through, super/subscript, caps, spacing | Font actions |
| Alignment, paragraph spacing, indents, borders, shading, drop caps | Paragraph actions |
| A4, orientation, margins, page/section breaks, columns, column breaks, page colour, hyphenation | Page layout actions |
| Header/footer text and alignment, page numbers | Header and footer actions |
| Table size, cells, alignment, merges, borders, row shading | Table actions |
| Pictures, captions, borders, SmartArt | Pictures and objects actions |
| Cover-page title/author/abstract and completed controls | Cover-page actions |
| Document properties | Document information actions |
| Bulleted/numbered lists and list levels | List actions |
| Bookmarks, bibliography, footnote text, TOC | Reference actions |
| Find/replace final result and comments | Editing and review actions |
| Heading 1/2/3, title, subtitle and normal styles | Styles actions |

## Requires Further Reusable Rules

| Existing marker outcome | Required extension |
| --- | --- |
| Exact Word cover-page gallery visual design | Word gallery designs are not consistently identifiable in DOCX XML; validate its visible fields and controls instead |
| Exact automatic-correct entry | Windows Word configuration check, not a submitted-DOCX check |

## Not Reliably Markable From A Single Uploaded DOCX

- Whether the learner used the Find and Replace dialog rather than manually editing text. The builder marks the final replacement outcome.
- The exact click path used in Word.
- Global Word AutoCorrect settings unless the learner workstation is inspected directly.

## Rule Design Standard

Every reusable action must have:

1. A defined Word outcome that can be checked from the completed `.docx`.
2. A controlled builder layout with dropdowns for Word attributes and free text only for task-specific content.
3. A marker test against a sample document before the action is shown to teachers.
