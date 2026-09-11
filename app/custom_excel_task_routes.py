"""Teacher-facing no-code builder for Excel upload tasks."""
import json
from datetime import datetime
from flask import redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename
from app.database import get_db, get_marking_db, get_teachers, get_user_role, log_activity

RULES = {
    "worksheet_exists": ("Workbook", "Worksheet exists", "worksheet_exists"), "worksheet_name": ("Workbook", "Worksheet name", "worksheet_name"),
    "cell_value": ("Cells", "Cell value", "cell_value"), "cell_contains": ("Cells", "Cell contains text", "cell_contains"), "formula_contains": ("Formulas", "Formula contains", "formula_contains"),
    "formula_exact": ("Formulas", "Exact formula", "formula_exact"), "formula_references": ("Formulas", "Formula references", "formula_references"), "formula_function": ("Formulas", "Formula function", "formula_function"), "formula_operator": ("Formulas", "Formula operator", "formula_operator"), "formula_absolute_reference": ("Formulas", "Formula absolute reference", "formula_absolute_reference"), "formula_result": ("Formulas", "Calculated formula result", "formula_result"),
    "number_format": ("Formatting", "Number format", "number_format"), "number_format_kind": ("Formatting", "Number format type", "number_format_kind"), "decimal_places": ("Formatting", "Exact decimal places", "decimal_places"), "font_name": ("Formatting", "Font name", "font_name"), "font_bold": ("Formatting", "Bold font", "font_bold"), "font_italic": ("Formatting", "Italic font", "font_italic"), "font_underline": ("Formatting", "Underlined font", "font_underline"), "font_color": ("Formatting", "Font colour", "font_color"),
    "fill_color": ("Formatting", "Cell fill colour", "fill_color"), "range_font_bold": ("Formatting", "Range font bold", "range_font_bold"), "range_fill_color": ("Formatting", "Range fill colour", "range_fill_color"), "border_side": ("Formatting", "Cell border side", "border_side"), "alignment": ("Formatting", "Cell alignment", "alignment"), "vertical_alignment": ("Formatting", "Vertical alignment", "vertical_alignment"), "wrap_text": ("Formatting", "Wrap text", "wrap_text"), "text_rotation": ("Formatting", "Text rotation", "text_rotation"), "indent": ("Formatting", "Cell indent", "indent"), "chart_count": ("Objects", "Minimum chart count", "chart_count"), "table_present": ("Tables", "Excel table present", "table_present"), "table_name": ("Tables", "Excel table name", "table_name"), "table_range": ("Tables", "Excel table range", "table_range"), "data_validation_range": ("Data", "Data validation range", "data_validation_range"),
    "font_size": ("Formatting", "Font size", "font_size"), "column_width": ("Layout", "Minimum column width", "column_width"), "row_height": ("Layout", "Minimum row height", "row_height"), "freeze_panes": ("Layout", "Freeze panes at cell", "freeze_panes"), "merged_range": ("Layout", "Merged cell range", "merged_range"), "sheet_tab_color": ("Workbook", "Worksheet tab colour", "sheet_tab_color"), "sheet_last": ("Workbook", "Worksheet is last", "sheet_last"), "table_style": ("Tables", "Excel table style", "table_style"),
    "sorted_range": ("Data", "Sorted column range", "sorted_range"), "multi_level_sort": ("Data", "Multi-level sort", "multi_level_sort"), "conditional_formatting_present": ("Data", "Conditional formatting present", "conditional_formatting_present"), "conditional_formatting_range": ("Data", "Conditional formatting range", "conditional_formatting_range"), "conditional_formatting_rule": ("Data", "Conditional-format rule", "conditional_formatting_rule"), "image_at_cell": ("Objects", "Image anchored at cell", "image_at_cell"), "image_dimensions": ("Objects", "Image dimensions", "image_dimensions"), "chart_title": ("Objects", "Chart title", "chart_title"), "chart_type": ("Objects", "Chart type", "chart_type"), "chart_legend_position": ("Objects", "Chart legend position", "chart_legend_position"), "chart_data_labels": ("Objects", "Chart data labels", "chart_data_labels"), "page_orientation": ("Print", "Page orientation", "page_orientation"), "fit_to_page": ("Print", "Fit worksheet to page", "fit_to_page"), "fit_to_width": ("Print", "Fit to pages wide", "fit_to_width"), "fit_to_height": ("Print", "Fit to pages tall", "fit_to_height"), "print_area": ("Print", "Print area", "print_area"), "print_title_rows": ("Print", "Repeated print title rows", "print_title_rows"), "page_margins": ("Print", "Page margin", "page_margins"), "manual_page_break": ("Print", "Manual page break", "manual_page_break"), "sheet_protected": ("Workbook", "Worksheet protection", "sheet_protected"),
}

def _rule(index):
    key=request.form.get(f"rule_{index}",""); description=request.form.get(f"description_{index}","").strip()
    if key not in RULES or not description:return None
    sheet=request.form.get(f"sheet_{index}","").strip(); cell=request.form.get(f"cell_{index}","").strip().upper(); value=request.form.get(f"value_{index}","").strip(); check_type=RULES[key][2]
    if check_type not in {"table_present","conditional_formatting_present"} and not value: raise ValueError(f"Criterion {index+1} needs an expected value.")
    if check_type in {"cell_value","cell_contains","formula_contains","formula_exact","formula_references","formula_function","formula_operator","formula_absolute_reference","formula_result","number_format","number_format_kind","decimal_places","font_name","font_bold","font_italic","font_underline","font_color","font_size","fill_color","range_font_bold","range_fill_color","border_side","alignment","vertical_alignment","wrap_text","text_rotation","indent","column_width","row_height"} and not cell: raise ValueError(f"Criterion {index+1} needs a cell reference.")
    if check_type=="chart_count": value=int(value)
    return {"question_number":str(index+1),"description":description,"domain":"excel","type":check_type,"target":{k:v for k,v in {"sheet":sheet,"cell":cell}.items() if v},"expected":value,"marks":1,"builder_rule":key,"builder_values":{"sheet":sheet,"cell":cell,"value":str(value)},"builder_target":""}

def register_custom_excel_task_routes(app):
 @app.route('/subjects/<int:subject_id>/custom_excel_task',methods=['GET','POST'])
 @app.route('/tasks/<int:task_id>/excel_builder/edit',methods=['GET','POST'])
 def custom_excel_task(subject_id=None,task_id=None):
  username=session.get('username')
  if not username or get_user_role(username) not in {'teacher','admin'}: return 'Access denied',403
  conn=get_db(); existing=None
  if task_id:
   existing=conn.execute("SELECT subject_id,name,assign_date,question_text,is_active,marking_setup_id FROM tasks WHERE id=? AND task_type='practical'",(task_id,)).fetchone()
   if not existing or not existing[5]: conn.close(); return 'This task does not have a no-code Excel marking setup.',404
   subject_id=existing[0]
  subject=conn.execute('SELECT name FROM subjects WHERE id=?',(subject_id,)).fetchone(); groups=[x[0] for x in conn.execute('SELECT DISTINCT group_name FROM users WHERE group_name IS NOT NULL ORDER BY group_name')]
  if not subject: conn.close(); return 'Subject not found',404
  criteria=[]
  if existing:
   mc=get_marking_db(); row=mc.execute('SELECT json_script_blob FROM marking_setups WHERE id=?',(existing[5],)).fetchone(); mc.close(); setup=json.loads((row[0] or b'{}').decode()) if row else {}
   if setup.get('program')!='excel': conn.close(); return 'This is not an Excel builder setup.',400
   criteria=setup.get('builder_criteria',[])
  error=None
  if request.method=='POST':
   try:
    title=request.form.get('title','').strip(); rules=[x for i in range(int(request.form.get('criterion_count','0') or 0)) if (x:=_rule(i))]
    if not title or not rules: raise ValueError('Task name and at least one marking criterion are required.')
    instructions=request.form.get('instructions','').strip(); now=datetime.now().isoformat()
    if existing:
     setup_id=existing[5]; setup={'task_name':title,'program':'excel','file':'student_file.xlsx','questions':rules,'builder_criteria':rules,'total_marks':len(rules)}; mc=get_marking_db(); mc.execute('UPDATE marking_setups SET title=?,notes=?,json_script_blob=?,updated_at=? WHERE id=?',(title,instructions,json.dumps(setup).encode(),now,setup_id));mc.commit();mc.close();conn.execute('UPDATE tasks SET name=?,assign_date=?,question_text=?,is_active=? WHERE id=?',(title,request.form.get('assign_date'),instructions,1 if request.form.get('is_active') else 0,task_id));conn.execute('DELETE FROM task_groups WHERE task_id=?',(task_id,));conn.executemany('INSERT INTO task_groups (task_id,group_name) VALUES (?,?)',[(task_id,x) for x in request.form.getlist('groups')]);conn.execute('DELETE FROM task_teachers WHERE task_id=?',(task_id,));conn.executemany('INSERT INTO task_teachers (task_id,teacher_username) VALUES (?,?)',[(task_id,x) for x in request.form.getlist('teachers')]);conn.commit()
    else:
     starter=request.files.get('starter_file')
     if not starter or not starter.filename or not starter.filename.lower().endswith(('.xlsx','.xlsm')): raise ValueError('An Excel starter workbook (.xlsx or .xlsm) is required.')
     blob,name=starter.read(),secure_filename(starter.filename); setup={'task_name':title,'program':'excel','file':'student_file.xlsx','questions':rules,'builder_criteria':rules,'total_marks':len(rules)}; mc=get_marking_db(); cur=mc.cursor();cur.execute('INSERT INTO marking_setups (title,created_by,created_at,updated_at,json_script_filename,json_script_blob,notes,starter_file_filename,starter_file_blob) VALUES (?,?,?,?,?,?,?,?,?)',(title,username,now,now,'excel_builder.json',json.dumps(setup).encode(),instructions,name,blob));setup_id=cur.lastrowid;mc.commit();mc.close();cur=conn.cursor();cur.execute("INSERT INTO tasks (subject_id,name,assign_date,created_by,created_at,marking_script,marking_setup_id,task_type,is_active,sample_file,sample_file_name,allow_multiple,max_attempts,question_text,practical_mode) VALUES (?,?,?,?,?,'marking_experiment_adapter',?,'practical',?,?,?,0,1,?,'upload')",(subject_id,title,request.form.get('assign_date'),username,now,setup_id,1 if request.form.get('is_active') else 0,blob,name,instructions));task_id=cur.lastrowid;conn.executemany('INSERT INTO task_groups (task_id,group_name) VALUES (?,?)',[(task_id,x) for x in request.form.getlist('groups')]);conn.executemany('INSERT INTO task_teachers (task_id,teacher_username) VALUES (?,?)',[(task_id,x) for x in request.form.getlist('teachers')]);conn.commit()
    log_activity(username,f'saved no-code Excel practical task {title}');return redirect(url_for('manage_tasks',subject_id=subject_id))
   except Exception as exc:error=str(exc)
  editing=None
  if existing: editing={'name':existing[1],'assign_date':existing[2],'instructions':existing[3],'is_active':existing[4],'groups':{x[0] for x in conn.execute('SELECT group_name FROM task_groups WHERE task_id=?',(task_id,))},'teachers':{x[0] for x in conn.execute('SELECT teacher_username FROM task_teachers WHERE task_id=?',(task_id,))}}
  conn.close();return render_template('custom_html_task.html',subject_id=subject_id,subject_name=subject[0],groups=groups,teachers=get_teachers(),rules=RULES,username=username,today=datetime.now().date().isoformat(),error=error,editing_task=editing,initial_criteria=criteria,builder_program='Excel')
