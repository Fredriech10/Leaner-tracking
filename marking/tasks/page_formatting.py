"""
Page Formatting Marking Script
Checks Word document formatting including page setup, borders, watermarks, headers/footers, and hyphenation
"""

def mark(filepath):
    """
    Mark a Word document for page formatting criteria
    Returns a dictionary with score, results, and feedback
    """
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        import os
        
        # Check if file exists
        if not os.path.exists(filepath):
            return {
                "task_name": "Page Formatting",
                "score": 0,
                "total": 15,
                "percentage": 0,
                "results": [],
                "error": "File not found"
            }
        
        # Load document
        try:
            doc = Document(filepath)
        except Exception as e:
            return {
                "task_name": "Page Formatting",
                "score": 0,
                "total": 15,
                "percentage": 0,
                "results": [],
                "error": f"Could not open document: {str(e)}"
            }
        
        results = []
        score = 0
        total = 15
        
        # Get sections (for page setup)
        section = doc.sections[0] if doc.sections else None
        
        # 1.1.1 Page Size & Orientation (2 marks)
        if section:
            # Check A4 size (210mm x 297mm = 11906200 EMUs x 16838040 EMUs)
            # Allow small tolerance
            page_width = section.page_width
            page_height = section.page_height
            
            # A4 in portrait: width ~8.27 inches, height ~11.69 inches
            # In EMUs: width ~11906200, height ~16838040
            is_a4 = (11800000 <= page_width <= 12000000) and (16700000 <= page_height <= 16900000)
            
            if is_a4:
                results.append({
                    "question": "1.1.1 Paper size set to A4",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.1.1 Paper size set to A4",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
            
            # Check Portrait orientation (height > width)
            is_portrait = page_height > page_width
            
            if is_portrait:
                results.append({
                    "question": "1.1.1 Orientation set to Portrait",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.1.1 Orientation set to Portrait",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
        else:
            results.append({
                "question": "1.1.1 Page Size & Orientation",
                "marks_available": 2,
                "marks_awarded": 0,
                "passed": False
            })
        
        # 1.1.2 Margins (2 marks)
        if section:
            # 2.5 cm = 25.4 mm = 1 inch = 914400 EMUs
            # 2.5 cm = 0.984 inches = ~895000 EMUs
            # Allow tolerance of ±50000 EMUs
            target_margin = 914400
            tolerance = 100000
            
            margins_correct = (
                abs(section.top_margin - target_margin) <= tolerance and
                abs(section.bottom_margin - target_margin) <= tolerance and
                abs(section.left_margin - target_margin) <= tolerance and
                abs(section.right_margin - target_margin) <= tolerance
            )
            
            if margins_correct:
                results.append({
                    "question": "1.1.2 Margins set to 2.5 cm (all sides)",
                    "marks_available": 2,
                    "marks_awarded": 2,
                    "passed": True
                })
                score += 2
            else:
                results.append({
                    "question": "1.1.2 Margins set to 2.5 cm (all sides)",
                    "marks_available": 2,
                    "marks_awarded": 0,
                    "passed": False
                })
        else:
            results.append({
                "question": "1.1.2 Margins",
                "marks_available": 2,
                "marks_awarded": 0,
                "passed": False
            })
        
        # 1.2.1 Page Border (3 marks)
        # Note: python-docx has limited support for reading borders
        # We'll check if borders exist in the XML
        try:
            from lxml import etree
            
            # Access the document XML
            doc_xml = doc._element
            namespaces = {
                'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            }
            
            # Check for page borders in section properties
            borders_found = doc_xml.xpath('//w:sectPr/w:pgBorders', namespaces=namespaces)
            
            if borders_found:
                border_elem = borders_found[0]
                
                # Check for double line style
                top_border = border_elem.find('.//w:top', namespaces)
                has_double = False
                if top_border is not None:
                    val = top_border.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                    if val and 'double' in val.lower():
                        has_double = True
                
                if has_double:
                    results.append({
                        "question": "1.2.1 Double-line style selected",
                        "marks_available": 1,
                        "marks_awarded": 1,
                        "passed": True
                    })
                    score += 1
                else:
                    results.append({
                        "question": "1.2.1 Double-line style selected",
                        "marks_available": 1,
                        "marks_awarded": 0,
                        "passed": False
                    })
                
                # Border applied to document
                results.append({
                    "question": "1.2.1 Border applied to document",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
                
                # Check for first page only setting
                offset_from = border_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}offsetFrom')
                display = border_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}display')
                
                # First page only is indicated by display="firstPage" or similar
                first_page_only = display == 'firstPage' if display else False
                
                if first_page_only:
                    results.append({
                        "question": "1.2.1 Setting 'This section - First page only' applied",
                        "marks_available": 1,
                        "marks_awarded": 1,
                        "passed": True
                    })
                    score += 1
                else:
                    results.append({
                        "question": "1.2.1 Setting 'This section - First page only' applied",
                        "marks_available": 1,
                        "marks_awarded": 0,
                        "passed": False
                    })
            else:
                # No borders found
                results.append({
                    "question": "1.2.1 Page Border (all criteria)",
                    "marks_available": 3,
                    "marks_awarded": 0,
                    "passed": False
                })
        except Exception as e:
            results.append({
                "question": "1.2.1 Page Border (could not check)",
                "marks_available": 3,
                "marks_awarded": 0,
                "passed": False
            })
        
        # 1.2.2 Watermark (3 marks)
        # Check for watermark in document
        try:
            # Watermarks are typically in headers
            watermark_found = False
            watermark_text_correct = False
            watermark_color_blue = False
            watermark_diagonal = False
            
            for section in doc.sections:
                header = section.header
                if header:
                    # Check header XML for watermark
                    header_xml = header._element
                    
                    # Look for shape with text "CAT TEST"
                    shapes = header_xml.xpath('.//v:shape', namespaces={'v': 'urn:schemas-microsoft-com:vml'})
                    
                    for shape in shapes:
                        # Check for text content
                        textpaths = shape.xpath('.//v:textpath', namespaces={'v': 'urn:schemas-microsoft-com:vml'})
                        for textpath in textpaths:
                            text = textpath.get('string', '')
                            if 'CAT TEST' in text.upper():
                                watermark_found = True
                                watermark_text_correct = True
                                
                                # Check color (blue)
                                fillcolor = shape.get('fillcolor', '')
                                if 'blue' in fillcolor.lower() or '#0000FF' in fillcolor.upper() or '#00F' in fillcolor.upper():
                                    watermark_color_blue = True
                                
                                # Check rotation for diagonal (typically 315 or -45 degrees)
                                rotation = shape.get('rotation', '')
                                style = shape.get('style', '')
                                if 'rotation' in style.lower() or rotation:
                                    watermark_diagonal = True
            
            if watermark_text_correct:
                results.append({
                    "question": "1.2.2 Text 'CAT TEST' inserted",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.2.2 Text 'CAT TEST' inserted",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
            
            if watermark_color_blue:
                results.append({
                    "question": "1.2.2 Colour set to Blue",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.2.2 Colour set to Blue",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
            
            if watermark_diagonal:
                results.append({
                    "question": "1.2.2 Layout set to Diagonal",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.2.2 Layout set to Diagonal",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
                
        except Exception as e:
            results.append({
                "question": "1.2.2 Watermark (could not check)",
                "marks_available": 3,
                "marks_awarded": 0,
                "passed": False
            })
        
        # 1.3.1 Header (1 mark)
        try:
            header_correct = False
            if doc.sections:
                header = doc.sections[0].header
                if header and header.paragraphs:
                    for para in header.paragraphs:
                        text = para.text.strip()
                        # Check if there's text and it's right-aligned
                        if text and para.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
                            header_correct = True
                            break
            
            if header_correct:
                results.append({
                    "question": "1.3.1 Name and Surname inserted and right-aligned",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.3.1 Name and Surname inserted and right-aligned",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
        except Exception as e:
            results.append({
                "question": "1.3.1 Header",
                "marks_available": 1,
                "marks_awarded": 0,
                "passed": False
            })
        
        # 1.3.2 Footer / Page Numbers (3 marks)
        try:
            footer_has_page_numbers = False
            footer_format_correct = False
            footer_centered = False
            
            if doc.sections:
                footer = doc.sections[0].footer
                if footer and footer.paragraphs:
                    for para in footer.paragraphs:
                        text = para.text.strip()
                        para_xml = para._element
                        
                        # Check for field codes (page numbers)
                        fldChars = para_xml.xpath('.//w:fldChar', namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                        instrTexts = para_xml.xpath('.//w:instrText', namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                        
                        if fldChars or instrTexts:
                            footer_has_page_numbers = True
                            
                            # Check for "Page X of Y" format
                            for instr in instrTexts:
                                instr_text = instr.text if instr.text else ''
                                if 'PAGE' in instr_text.upper() and 'NUMPAGES' in instr_text.upper():
                                    footer_format_correct = True
                        
                        # Check if text contains page number indicators
                        if 'page' in text.lower() or text:
                            if para.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                                footer_centered = True
            
            if footer_has_page_numbers:
                results.append({
                    "question": "1.3.2 Automatic page numbers added",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.3.2 Automatic page numbers added",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
            
            if footer_format_correct:
                results.append({
                    "question": "1.3.2 Format 'Page X of Y' used",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.3.2 Format 'Page X of Y' used",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
            
            if footer_centered:
                results.append({
                    "question": "1.3.2 Center-aligned in footer",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.3.2 Center-aligned in footer",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
                
        except Exception as e:
            results.append({
                "question": "1.3.2 Footer / Page Numbers",
                "marks_available": 3,
                "marks_awarded": 0,
                "passed": False
            })
        
        # 1.4.1 Hyphenation (1 mark)
        try:
            # Check document settings for hyphenation
            doc_xml = doc._element
            settings = doc_xml.xpath('//w:settings', namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
            
            hyphenation_enabled = False
            if settings:
                # Look for autoHyphenation setting
                auto_hyphen = settings[0].xpath('.//w:autoHyphenation', namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
                if auto_hyphen:
                    val = auto_hyphen[0].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                    if val is None or val == '1' or val.lower() == 'true':
                        hyphenation_enabled = True
            
            if hyphenation_enabled:
                results.append({
                    "question": "1.4.1 Automatic hyphenation enabled",
                    "marks_available": 1,
                    "marks_awarded": 1,
                    "passed": True
                })
                score += 1
            else:
                results.append({
                    "question": "1.4.1 Automatic hyphenation enabled",
                    "marks_available": 1,
                    "marks_awarded": 0,
                    "passed": False
                })
        except Exception as e:
            results.append({
                "question": "1.4.1 Hyphenation",
                "marks_available": 1,
                "marks_awarded": 0,
                "passed": False
            })
        
        # Calculate percentage
        percentage = round((score / total) * 100) if total > 0 else 0
        
        return {
            "task_name": "Page Formatting",
            "score": score,
            "total": total,
            "percentage": percentage,
            "results": results,
            "error": None
        }
        
    except ImportError:
        return {
            "task_name": "Page Formatting",
            "score": 0,
            "total": 15,
            "percentage": 0,
            "results": [],
            "error": "Required library 'python-docx' not installed. Please install it using: pip install python-docx lxml"
        }
    except Exception as e:
        return {
            "task_name": "Page Formatting",
            "score": 0,
            "total": 15,
            "percentage": 0,
            "results": [],
            "error": f"Unexpected error: {str(e)}"
        }
