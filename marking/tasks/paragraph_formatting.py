"""
Paragraph Formatting Marking Script
"""

def mark(filepath):
    try:
        from docx import Document
        import os

        if not os.path.exists(filepath):
            return {"task_name": "Paragraph Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": "File not found"}

        try:
            doc = Document(filepath)
        except Exception as e:
            return {"task_name": "Paragraph Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": f"Could not open document: {str(e)}"}

        results = []
        score = 0
        total = 15
        WN = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        paras = doc.paragraphs

        def after_heading(keyword):
            """First non-empty paragraph after a heading containing keyword."""
            for i, p in enumerate(paras):
                if keyword.lower() in p.text.lower() and 'heading' in p.style.name.lower():
                    for j in range(i + 1, len(paras)):
                        if paras[j].text.strip():
                            return paras[j]
            return None

        def starts_with(keyword):
            for p in paras:
                if p.text.strip().lower().startswith(keyword.lower()):
                    return p
            return None

        def pPr(para):
            return para._element.find(WN + 'pPr') if para else None

        def child(el, tag):
            return el.find(WN + tag) if el is not None else None

        def attr(el, name, default='0'):
            return el.get(WN + name, default) if el is not None else default

        # --- 1.1.1 Justified alignment under "Introduction" (1 mark) ---
        try:
            para = after_heading('Introduction')
            jc = child(pPr(para), 'jc')
            ok = attr(jc, 'val') == 'both'
            _add(results, "1.1.1 Paragraph under 'Introduction' set to Justified", 1, ok)
            if ok: score += 1
        except Exception as e:
            results.append({"question": "1.1.1 Justified alignment", "marks_available": 1, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.2.1 Left indent 1.5 cm on "Electronic waste..." (2 marks) ---
        try:
            para = starts_with('Electronic waste')
            ind = child(pPr(para), 'ind')
            left = int(attr(ind, 'left'))
            ok = abs(left - 851) <= 50  # 1.5cm = 851 twips
            _add(results, "1.2.1 'Electronic waste' paragraph indented 1.5 cm from left", 2, ok)
            if ok: score += 2
        except Exception as e:
            results.append({"question": "1.2.1 Left indentation 1.5 cm", "marks_available": 2, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.2.2 First line indent 0.5 cm under "Global Trends" (2 marks) ---
        try:
            para = after_heading('Global Trends')
            ind = child(pPr(para), 'ind')
            first = int(attr(ind, 'firstLine'))
            ok = abs(first - 284) <= 50  # 0.5cm = 284 twips
            _add(results, "1.2.2 First line indent 0.5 cm under 'Global Trends'", 2, ok)
            if ok: score += 2
        except Exception as e:
            results.append({"question": "1.2.2 First line indent 0.5 cm", "marks_available": 2, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.3.1 Line spacing Exactly 15pt on paragraph under "Health Risks" (2 marks) ---
        try:
            para = after_heading('Health Risks')
            sp = child(pPr(para), 'spacing')
            line_rule = attr(sp, 'lineRule')
            line_val = int(attr(sp, 'line'))
            exact_ok = line_rule == 'exact'
            spacing_ok = exact_ok and abs(line_val - 300) <= 10  # 15pt = 300 twips
            _add(results, "1.3.1 Line spacing set to 'Exactly'", 1, exact_ok)
            if exact_ok: score += 1
            _add(results, "1.3.1 Line spacing measurement set to 15 pt", 1, spacing_ok)
            if spacing_ok: score += 1
        except Exception as e:
            results.append({"question": "1.3.1 Line spacing Exactly 15pt", "marks_available": 2, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.3.2 Spacing Before 12pt under "Conclusion" (2 marks) ---
        try:
            # Skip drop cap frame paragraphs — find first para after Conclusion without framePr
            para = None
            for i, p in enumerate(paras):
                if 'conclusion' in p.text.lower() and 'heading' in p.style.name.lower():
                    for j in range(i + 1, len(paras)):
                        pp = pPr(paras[j])
                        if paras[j].text.strip() and child(pp, 'framePr') is None:
                            para = paras[j]
                            break
                    break
            sp = child(pPr(para), 'spacing')
            before = int(attr(sp, 'before'))
            ok = abs(before - 240) <= 20  # 12pt = 240 twips
            _add(results, "1.3.2 Spacing 'Before' set to 12 pt under 'Conclusion'", 2, ok)
            if ok: score += 2
        except Exception as e:
            results.append({"question": "1.3.2 Spacing before 12pt", "marks_available": 2, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.4.1 Blue 3pt border under "Environmental Impact" (2 marks) ---
        try:
            para = after_heading('Environmental Impact')
            pBdr = child(pPr(para), 'pBdr')
            border_applied = False
            border_correct = False

            if pBdr is not None:
                sides = [pBdr.find(WN + s) for s in ('top', 'bottom', 'left', 'right')]
                border_applied = all(s is not None for s in sides)
                if border_applied:
                    top = sides[0]
                    color = attr(top, 'color').lower()
                    sz = int(attr(top, 'sz'))
                    # sz=24 = 3pt (in eighths of a point), colour 0070c0 is Word's blue
                    is_blue = color in ('0000ff', '0070c0', '4472c4') or color.startswith('00')
                    is_3pt = abs(sz - 24) <= 4
                    border_correct = is_blue and is_3pt

            _add(results, "1.4.1 Border applied around paragraph under 'Environmental Impact'", 1, border_applied)
            if border_applied: score += 1
            _add(results, "1.4.1 Border colour Blue and width 3 pt", 1, border_correct)
            if border_correct: score += 1
        except Exception as e:
            results.append({"question": "1.4.1 Paragraph border", "marks_available": 2, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.4.2 Light Grey shading on same paragraph (1 mark) ---
        try:
            para = after_heading('Environmental Impact')
            shd = child(pPr(para), 'shd')
            fill = attr(shd, 'fill').lower()
            # Light grey values: bfbfbf, c0c0c0, d3d3d3, d9d9d9, e0e0e0, cccccc, a6a6a6
            light_greys = ('bfbfbf', 'c0c0c0', 'd3d3d3', 'd9d9d9', 'e0e0e0',
                           'cccccc', 'a6a6a6', 'b2b2b2', 'f2f2f2', 'e7e7e7')
            ok = fill in light_greys
            _add(results, "1.4.2 Light Grey shading applied to paragraph", 1, ok)
            if ok: score += 1
        except Exception as e:
            results.append({"question": "1.4.2 Light grey shading", "marks_available": 1, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.5.1 Drop Cap on first paragraph of the document body (3 marks) ---
        try:
            # Drop cap splits into its own paragraph — find framePr with dropCap
            drop_applied = False
            drop_position = False
            drop_lines = False

            for p in paras:
                pp = pPr(p)
                frame = child(pp, 'framePr') if pp is not None else None
                if frame is not None and frame.get(WN + 'dropCap') is not None:
                    drop_applied = True
                    drop_position = attr(frame, 'dropCap') == 'drop'
                    drop_lines = attr(frame, 'lines') == '3'
                    break

            _add(results, "1.5.1 Drop Cap applied to first letter", 1, drop_applied)
            if drop_applied: score += 1
            _add(results, "1.5.1 Drop Cap position set to 'Dropped'", 1, drop_position)
            if drop_position: score += 1
            _add(results, "1.5.1 Drop Cap lines set to 3", 1, drop_lines)
            if drop_lines: score += 1
        except Exception as e:
            results.append({"question": "1.5.1 Drop Cap", "marks_available": 3, "marks_awarded": 0, "passed": False, "error": str(e)})

        percentage = round((score / total) * 100) if total > 0 else 0
        return {"task_name": "Paragraph Formatting", "score": score, "total": total, "percentage": percentage, "results": results, "error": None}

    except ImportError as e:
        return {"task_name": "Paragraph Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": f"Missing library: {str(e)}. Run: pip install python-docx"}
    except Exception as e:
        return {"task_name": "Paragraph Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": f"Unexpected error: {str(e)}"}


def _add(results, question, marks, passed):
    results.append({
        "question": question,
        "marks_available": marks,
        "marks_awarded": marks if passed else 0,
        "passed": passed
    })
