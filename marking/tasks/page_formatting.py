"""
Page Formatting Marking Script
"""

def mark(filepath):
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from lxml import etree
        import os

        if not os.path.exists(filepath):
            return {"task_name": "Page Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": "File not found"}

        try:
            doc = Document(filepath)
        except Exception as e:
            return {"task_name": "Page Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": f"Could not open document: {str(e)}"}

        results = []
        score = 0
        total = 15
        W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        WN = '{' + W + '}'

        section = doc.sections[0] if doc.sections else None

        # --- 1.1.1 Page Size & Orientation (2 marks) ---
        if section:
            pw = section.page_width
            ph = section.page_height
            # A4: 210mm x 297mm = 7559055 x 10692914 EMU, allow ±200000 tolerance
            is_a4 = (7350000 <= pw <= 7750000) and (10480000 <= ph <= 10900000)
            _add(results, "1.1.1 Paper size set to A4", 1, is_a4)
            if is_a4: score += 1

            is_portrait = ph > pw
            _add(results, "1.1.1 Orientation set to Portrait", 1, is_portrait)
            if is_portrait: score += 1
        else:
            results.append({"question": "1.1.1 Page Size & Orientation", "marks_available": 2, "marks_awarded": 0, "passed": False})

        # --- 1.1.2 Margins (2 marks) ---
        if section:
            # 2.5cm = 900430 EMU (confirmed from actual document)
            target = 900430
            tol = 100000
            ok = all(abs(m - target) <= tol for m in [
                section.top_margin, section.bottom_margin,
                section.left_margin, section.right_margin
            ])
            _add(results, "1.1.2 Margins set to 2.5 cm (all sides)", 2, ok)
            if ok: score += 2
        else:
            results.append({"question": "1.1.2 Margins", "marks_available": 2, "marks_awarded": 0, "passed": False})

        # --- 1.2.1 Page Border (3 marks) ---
        try:
            borders_list = doc._element.findall('.//' + WN + 'pgBorders')
            if borders_list:
                be = borders_list[0]
                top    = be.find(WN + 'top')
                bottom = be.find(WN + 'bottom')
                left   = be.find(WN + 'left')
                right  = be.find(WN + 'right')

                all_exist = all(x is not None for x in [top, bottom, left, right])
                _add(results, "1.2.1 Border applied to document", 1, all_exist)
                if all_exist: score += 1

                has_double = any(
                    x is not None and 'double' in (x.get(WN + 'val') or '').lower()
                    for x in [top, bottom, left, right]
                )
                _add(results, "1.2.1 Double-line style selected", 1, has_double)
                if has_double: score += 1

                display = be.get(WN + 'display')
                first_page = display == 'firstPage'
                _add(results, "1.2.1 Setting 'This section - First page only' applied", 1, first_page)
                if first_page: score += 1
            else:
                results.append({"question": "1.2.1 Page Border (all criteria)", "marks_available": 3, "marks_awarded": 0, "passed": False})
        except Exception as e:
            results.append({"question": "1.2.1 Page Border", "marks_available": 3, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.2.2 Watermark (3 marks) ---
        try:
            watermark_text = False
            watermark_blue = False
            watermark_diagonal = False
            VN = '{urn:schemas-microsoft-com:vml}'

            for sec in doc.sections:
                hdr = sec.header
                if not hdr:
                    continue
                for shape in hdr._element.iter(VN + 'shape'):
                    for tp in shape.iter(VN + 'textpath'):
                        if 'CAT TEST' in (tp.get('string', '')).upper():
                            watermark_text = True
                            fillcolor = shape.get('fillcolor', '').lower().strip()
                            # Pass if colour is not the default grey
                            default_greys = ('', '#c0c0c0', 'silver', 'gray', 'grey', '#808080', 'auto')
                            if fillcolor not in default_greys:
                                watermark_blue = True
                            if 'rotation' in shape.get('style', '').lower():
                                watermark_diagonal = True

            _add(results, "1.2.2 Text 'CAT TEST' inserted", 1, watermark_text)
            if watermark_text: score += 1
            _add(results, "1.2.2 Colour changed from default (set to Blue)", 1, watermark_blue)
            if watermark_blue: score += 1
            _add(results, "1.2.2 Layout set to Diagonal", 1, watermark_diagonal)
            if watermark_diagonal: score += 1
        except Exception as e:
            results.append({"question": "1.2.2 Watermark", "marks_available": 3, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.3.1 Header (1 mark) ---
        try:
            header_ok = False
            if doc.sections:
                hdr = doc.sections[0].header
                if hdr:
                    for para in hdr.paragraphs:
                        text = para.text.strip()
                        pPr = para._element.find(WN + 'pPr')
                        jc = pPr.find(WN + 'jc') if pPr is not None else None
                        jc_val = jc.get(WN + 'val') if jc is not None else None
                        is_right = (jc_val == 'right') or (para.alignment == WD_ALIGN_PARAGRAPH.RIGHT)
                        if text and is_right:
                            header_ok = True
                            break
            _add(results, "1.3.1 Name and Surname inserted and right-aligned", 1, header_ok)
            if header_ok: score += 1
        except Exception as e:
            results.append({"question": "1.3.1 Header", "marks_available": 1, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.3.2 Footer / Page Numbers (3 marks) ---
        try:
            has_page = False
            has_format = False
            is_centered = False

            if doc.sections:
                ftr = doc.sections[0].footer
                if ftr:
                    ftr_xml = ftr._element
                    instr_texts = [el.text or '' for el in ftr_xml.iter(WN + 'instrText')]
                    all_instr = ' '.join(instr_texts).upper()

                    has_page_field = ' PAGE ' in (' ' + all_instr + ' ')
                    has_numpages_field = 'NUMPAGES' in all_instr

                    if has_page_field:
                        has_page = True

                    all_text = ''.join(t.text or '' for t in ftr_xml.iter(WN + 't'))
                    if has_page_field and has_numpages_field and 'of' in all_text.lower():
                        has_format = True

                    for p in ftr_xml.iter(WN + 'p'):
                        pPr = p.find(WN + 'pPr')
                        jc = pPr.find(WN + 'jc') if pPr is not None else None
                        if jc is not None and jc.get(WN + 'val') == 'center':
                            is_centered = True
                            break

            _add(results, "1.3.2 Automatic page numbers added", 1, has_page)
            if has_page: score += 1
            _add(results, "1.3.2 Format 'Page X of Y' used", 1, has_format)
            if has_format: score += 1
            _add(results, "1.3.2 Center-aligned in footer", 1, is_centered)
            if is_centered: score += 1
        except Exception as e:
            results.append({"question": "1.3.2 Footer / Page Numbers", "marks_available": 3, "marks_awarded": 0, "passed": False, "error": str(e)})

        # --- 1.4.1 Hyphenation (1 mark) ---
        try:
            hyphen_ok = False
            settings_part = doc.part.part_related_by(
                'http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings'
            )
            auto_hyph = settings_part._element.findall('.//' + WN + 'autoHyphenation')
            if auto_hyph:
                val = auto_hyph[0].get(WN + 'val')
                if val is None or val in ('1', 'true', 'on'):
                    hyphen_ok = True
            _add(results, "1.4.1 Automatic hyphenation enabled", 1, hyphen_ok)
            if hyphen_ok: score += 1
        except Exception as e:
            results.append({"question": "1.4.1 Hyphenation", "marks_available": 1, "marks_awarded": 0, "passed": False, "error": str(e)})

        percentage = round((score / total) * 100) if total > 0 else 0
        return {"task_name": "Page Formatting", "score": score, "total": total, "percentage": percentage, "results": results, "error": None}

    except ImportError as e:
        return {"task_name": "Page Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": f"Missing library: {str(e)}. Run: pip install python-docx lxml"}
    except Exception as e:
        return {"task_name": "Page Formatting", "score": 0, "total": 15, "percentage": 0, "results": [], "error": f"Unexpected error: {str(e)}"}


def _add(results, question, marks, passed):
    results.append({
        "question": question,
        "marks_available": marks,
        "marks_awarded": marks if passed else 0,
        "passed": passed
    })
