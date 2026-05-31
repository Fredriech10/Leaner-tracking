# Task TODO - Marking Experiment validation

- [ ] Inspect current marking experiment runner and how it loads structured expectations / task JSON
- [ ] Identify which “docx available in folder structure” correspond to question paper / memo / learner data, and how engine maps rules to files
- [ ] Run the Marking Experiment program against existing `.docx` samples and capture output vs expected (aim: all 100%)
- [ ] Update code to match the new `structure_expectations.json` format (rule mapping, domains/types, targets)
- [ ] Adjust word-check rules for:
  - [ ] “appropriate data” -> pass when not default
  - [ ] color changes -> pass when not default
  - [ ] cover pages -> pass when correct template elements exist
- [ ] Re-run marking after each code change until the `.docx` set scores 100%
- [ ] Summarize the final code changes and how to run the experiment again

