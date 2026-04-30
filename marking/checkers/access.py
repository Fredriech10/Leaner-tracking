"""
checkers/access.py
Reusable check functions for Access (.accdb) assignments.

Tables / Queries / Fields / Records  →  pyodbc
Forms / Reports                       →  COM automation via win32com
                                         (requires Access 2019 installed)
"""

import pyodbc
import subprocess
import tempfile
import os


# ── Helper: pyodbc connection ─────────────────────────────────────────────────

def _connect(filepath):
    conn_str = (
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={filepath};"
    )
    return pyodbc.connect(conn_str)


# ── Table checks ──────────────────────────────────────────────────────────────

def table_exists(filepath, table_name):
    """Check if a table exists in the database (case-insensitive)."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    tables = [row.table_name.upper() for row in cursor.tables(tableType="TABLE")]
    conn.close()
    return table_name.upper() in tables


def table_count(filepath, expected_count):
    """Check if the database has an exact number of user tables."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    tables = [row for row in cursor.tables(tableType="TABLE")]
    conn.close()
    return len(tables) == expected_count


def field_exists(filepath, table_name, field_name):
    """Check if a field exists in a specific table (case-insensitive)."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    columns = [row.column_name.upper() for row in cursor.columns(table=table_name)]
    conn.close()
    return field_name.upper() in columns


def field_count(filepath, table_name, expected_count):
    """Check if a table has an exact number of fields."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    columns = [row for row in cursor.columns(table=table_name)]
    conn.close()
    return len(columns) == expected_count


def field_type(filepath, table_name, field_name, expected_type):
    """
    Check if a field has a specific data type.
    expected_type examples: 'TEXT', 'NUMBER', 'DATE/TIME', 'AUTONUMBER'
    Uses ODBC type names — check pyodbc docs for full list.
    """
    conn = _connect(filepath)
    cursor = conn.cursor()
    for row in cursor.columns(table=table_name):
        if row.column_name.upper() == field_name.upper():
            conn.close()
            return row.type_name.upper() == expected_type.upper()
    conn.close()
    return False


def record_count(filepath, table_name, expected_count):
    """Check if a table has an exact number of records."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    count = cursor.fetchone()[0]
    conn.close()
    return count == expected_count


def record_count_at_least(filepath, table_name, minimum):
    """Check if a table has at least a minimum number of records."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    count = cursor.fetchone()[0]
    conn.close()
    return count >= minimum


def field_has_primary_key(filepath, table_name, field_name):
    """Check if a field is the primary key of a table."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    pk_columns = [row.column_name.upper() for row in cursor.primaryKeys(table=table_name)]
    conn.close()
    return field_name.upper() in pk_columns


def relationship_exists(filepath, table1, table2):
    """
    Check if a relationship exists between two tables.
    Uses pyodbc foreignKeys.
    """
    conn = _connect(filepath)
    cursor = conn.cursor()
    fk_tables = [row.fktable_name.upper() for row in cursor.foreignKeys(table=table1)]
    conn.close()
    return table2.upper() in fk_tables


# ── Query checks ──────────────────────────────────────────────────────────────

def query_exists(filepath, query_name):
    """Check if a query (view) exists in the database (case-insensitive)."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    views = [row.table_name.upper() for row in cursor.tables(tableType="VIEW")]
    conn.close()
    return query_name.upper() in views


def query_count(filepath, expected_count):
    """Check if the database has an exact number of queries."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    views = [row for row in cursor.tables(tableType="VIEW")]
    conn.close()
    return len(views) == expected_count


def query_returns_rows(filepath, query_name):
    """Check if a query returns at least one row."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM [{query_name}]")
    row = cursor.fetchone()
    conn.close()
    return row is not None


def query_field_exists(filepath, query_name, field_name):
    """Check if a query result contains a specific field/column."""
    conn = _connect(filepath)
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM [{query_name}]")
    columns = [desc[0].upper() for desc in cursor.description]
    conn.close()
    return field_name.upper() in columns


# ── Form / Report checks via COM automation ───────────────────────────────────
# These use a VBScript helper called via subprocess.
# Access 2019 must be installed on the marking machine.

def _run_vbs(script_content):
    """
    Write a VBScript to a temp file, run it with wscript,
    and return the stdout output as a string.
    """
    with tempfile.NamedTemporaryFile(suffix=".vbs", mode="w", delete=False) as f:
        f.write(script_content)
        vbs_path = f.name

    try:
        result = subprocess.run(
            ["cscript", "//NoLogo", vbs_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR:{e}"
    finally:
        os.unlink(vbs_path)


def form_exists(filepath, form_name):
    """Check if a form exists in the Access database."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
Dim frm
For Each frm In acc.CurrentProject.AllForms
    If UCase(frm.Name) = UCase("{form_name}") Then
        WScript.Echo "FOUND"
    End If
Next
acc.Quit
Set acc = Nothing
"""
    return _run_vbs(script) == "FOUND"


def report_exists(filepath, report_name):
    """Check if a report exists in the Access database."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
Dim rpt
For Each rpt In acc.CurrentProject.AllReports
    If UCase(rpt.Name) = UCase("{report_name}") Then
        WScript.Echo "FOUND"
    End If
Next
acc.Quit
Set acc = Nothing
"""
    return _run_vbs(script) == "FOUND"


def form_record_source(filepath, form_name, expected_source):
    """Check if a form is bound to a specific table or query."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
acc.DoCmd.OpenForm "{form_name}", 1  ' acDesign = 1
Dim src
src = acc.Forms("{form_name}").RecordSource
WScript.Echo src
acc.DoCmd.Close 2, "{form_name}"
acc.Quit
Set acc = Nothing
"""
    result = _run_vbs(script)
    return result.upper() == expected_source.upper()


def report_record_source(filepath, report_name, expected_source):
    """Check if a report is bound to a specific table or query."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
acc.DoCmd.OpenReport "{report_name}", 1  ' acViewDesign = 1
Dim src
src = acc.Reports("{report_name}").RecordSource
WScript.Echo src
acc.DoCmd.Close 3, "{report_name}"
acc.Quit
Set acc = Nothing
"""
    result = _run_vbs(script)
    return result.upper() == expected_source.upper()


def form_control_exists(filepath, form_name, control_name):
    """Check if a specific control exists on a form."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
acc.DoCmd.OpenForm "{form_name}", 1
Dim ctrl
For Each ctrl In acc.Forms("{form_name}").Controls
    If UCase(ctrl.Name) = UCase("{control_name}") Then
        WScript.Echo "FOUND"
    End If
Next
acc.DoCmd.Close 2, "{form_name}"
acc.Quit
Set acc = Nothing
"""
    return _run_vbs(script) == "FOUND"


def form_control_source(filepath, form_name, control_name, expected_source):
    """Check if a form control is bound to a specific field."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
acc.DoCmd.OpenForm "{form_name}", 1
Dim ctrl
Set ctrl = acc.Forms("{form_name}").Controls("{control_name}")
WScript.Echo ctrl.ControlSource
acc.DoCmd.Close 2, "{form_name}"
acc.Quit
Set acc = Nothing
"""
    result = _run_vbs(script)
    return result.upper() == expected_source.upper()


def report_control_exists(filepath, report_name, control_name):
    """Check if a specific control exists on a report."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
acc.DoCmd.OpenReport "{report_name}", 1
Dim ctrl
For Each ctrl In acc.Reports("{report_name}").Controls
    If UCase(ctrl.Name) = UCase("{control_name}") Then
        WScript.Echo "FOUND"
    End If
Next
acc.DoCmd.Close 3, "{report_name}"
acc.Quit
Set acc = Nothing
"""
    return _run_vbs(script) == "FOUND"


def form_count(filepath, expected_count):
    """Check if the database has an exact number of forms."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
WScript.Echo acc.CurrentProject.AllForms.Count
acc.Quit
Set acc = Nothing
"""
    result = _run_vbs(script)
    try:
        return int(result) == expected_count
    except ValueError:
        return False


def report_count(filepath, expected_count):
    """Check if the database has an exact number of reports."""
    script = f"""
Dim acc
On Error Resume Next
Set acc = CreateObject("Access.Application")
acc.OpenCurrentDatabase "{filepath}"
WScript.Echo acc.CurrentProject.AllReports.Count
acc.Quit
Set acc = Nothing
"""
    result = _run_vbs(script)
    try:
        return int(result) == expected_count
    except ValueError:
        return False
