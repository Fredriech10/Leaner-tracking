# Marking_Experiment Review TODOs

- [x] Inspect project structure and entry points — completed
- [x] Static/read-only review of core modules — completed
- [x] Run quick runtime smoke (if safe) — completed
- [x] Write concise feedback and improvement suggestions — completed

## Prioritized aspects for 100% effectiveness (most important first)

### Tier 1: Core Functionality (Word must work reliably)
1. **Make marking deterministic and complete for Word** — All checks must produce consistent, reproducible results
   - [x] DONE: Created infrastructure (utils.py, targeting.py, task_validator.py)
   - [x] DONE: Integrated into word_checker.py (numeric comparisons use tolerances, targeting uses fallbacks)
   - [ ] TODO: End-to-end test with real DOCX fixtures
2. **Implement/finish all WordChecker check types** — Complete all domain checks (paragraph_formatting, font, table, list, object, advanced)
   - [ ] TODO: Verify all 24 checks work end-to-end with new infrastructure
3. **Remove heuristic guessing, use reliable OpenXML parsing** — Replace fragile image/smartart/watermark heuristics with proper XML extraction
   - [ ] TODO: Implement proper XML extraction for image/smartart/watermark checks
4. **Remove brittleness in "targeting" (where to check)** — Targeting strategies must reliably find the right paragraph/table/object
   - [x] DONE: Created targeting.py with Locator class, 6-level fallback hierarchy, fuzzy matching
5. **Strengthen paragraph/table location strategies** — Beyond `after_heading` and fixed indices; add context-aware matching
   - [x] DONE: find_best_candidate_paragraph() with 6 strategies, find_table() with robust search
6. **Add fallback locators** — Match by style name + nearby text, fuzzy heading match, "best candidate" paragraph selection
   - [x] DONE: Locator class, string_similarity() with 0.75 threshold, find_best_candidate_paragraph()

### Tier 2: Numeric & Comparison Stability
7. **Standardize unit conversions** — Centralized conversion (pt/cm/lines/EMU) to avoid precision errors
   - [x] DONE: Created utils.py with pt_to_emu(), emu_to_pt(), cm_to_emu(), emu_to_cm(), etc.
   - [x] DONE: All conversions deterministic and reversible
8. **Apply consistent tolerances** — Font size, spacing, indent, border width comparisons with defined tolerances (not exact float equality)
   - [x] DONE: Created TOLERANCE_PT=0.5, TOLERANCE_CM=0.05 in utils.py
   - [x] DONE: Integrated into word_checker.py (all numeric checks use compare_numeric with tolerances)
9. **Stabilize numeric comparisons** — Handle rounding, floating-point precision, and unit conversions uniformly
   - [x] DONE: Created compare_numeric() function in utils.py
   - [x] DONE: word_checker.py uses compare_numeric() for all: size, space_before/after, first_line_indent, line_spacing

### Tier 3: Parser & Generation Pipeline
10. **Fix marksheet-to-rules pipeline** — Ensure generated task JSON is valid and complete
11. **Make MarksheetParser robust** — Validate LLM output heavily; fallback safely if LLM fails
12. **Make heuristic memo-table parsing layout-agnostic** — Handle various table formats, column orders, spacing
13. **Complete the rest of programs or constrain generation** — Implement real Excel/HTML/Access checkers, or prevent generation of rules for unimplemented types
14. **Ensure FEEDBACK_TEMPLATES coverage** — Every (domain, type) pair must have pass/fail feedback messages

### Tier 4: Document Structure Robustness
15. **Harden header/footer/document-part scanning** — Handle first-page-only, even/odd, linked headers/footers correctly
16. **Handle real-world DOCX edge cases** — Missing theme, corrupted XML, unsupported formatting, large files, encoding issues

### Tier 5: Regression & Validation
17. **Add regression test corpus** — Build collection of DOCX samples + expected outputs; test after improvements
18. **End-to-end workflow test** — Load task JSON, run against DOCX, validate scoring and feedback

### Tier 6: Developer Experience
19. **Add README & usage docs** — Setup, backend config, example workflow, expected outputs
20. **Pin dependencies** — Exact versions in requirements.txt
21. **Add logging** — Replace silent failures; log errors with context
22. **Remove dead code** — Delete unused functions, consolidate duplicate logic
23. **Add unit tests** — marksheet_parser, engine, checker logic
24. **CI/CD pipeline** — Automated tests on push
