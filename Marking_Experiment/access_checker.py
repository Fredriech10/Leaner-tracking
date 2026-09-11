"""Reusable DAO checks for no-code Microsoft Access practical tasks."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pythoncom
import win32com.client as win32

from .checker_types import BaseChecker, CheckerResult


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _property_value(item: Any, name: str, default: Any = None) -> Any:
    """Read optional DAO/Access properties without failing the whole criterion."""
    try:
        return item.Properties(name).Value
    except Exception:
        return default


def _field(table: Any, name: str) -> Any:
    try:
        return table.Fields(name) if table else None
    except Exception:
        return None


def _sql_tokens(value: Any) -> list[str]:
    """Split teacher-entered SQL tokens while preserving Access identifiers."""
    return [_normalise(token) for token in str(value or "").split(",") if _normalise(token)]


class AccessChecker(BaseChecker):
    program = "access"

    def check(self, domain: str, check_type: str, target: Dict[str, Any], expected: Any, file_path: Path) -> CheckerResult:
        pythoncom.CoInitialize()
        db = None
        try:
            engine = win32.Dispatch("DAO.DBEngine.120")
            db = engine.OpenDatabase(str(file_path.resolve()))
            table_name = str((target or {}).get("table", ""))
            field_name = str((target or {}).get("field", ""))
            wanted = str(expected or "").strip()
            actual: Any = None
            passed = False
            tables = {str(db.TableDefs(index).Name).casefold(): db.TableDefs(index) for index in range(db.TableDefs.Count) if not str(db.TableDefs(index).Name).startswith("MSys")}
            if check_type == "table_exists":
                actual = list(tables)
                passed = wanted.casefold() in tables
            elif check_type.startswith("field_"):
                table = tables.get(table_name.casefold())
                field = _field(table, field_name)
                if check_type == "field_exists":
                    actual = field is not None
                    passed = actual
                elif check_type == "field_size":
                    actual = field.Size if field else None
                    passed = actual is not None and int(actual) == int(expected)
                elif check_type == "field_data_type":
                    actual = field.Type if field else None
                    types = {
                        "yes/no": 1, "boolean": 1, "byte": 2, "integer": 3,
                        "long integer": 4, "number": 4, "single": 6, "double": 7,
                        "date/time": 8, "date": 8, "currency": 5, "autonumber": 4,
                        "text": 10, "short text": 10, "long text": 12, "memo": 12,
                        "hyperlink": 12, "attachment": 101,
                    }
                    expected_type = types.get(wanted.casefold(), int(expected) if wanted.isdigit() else -1)
                    passed = actual is not None and int(actual) == expected_type
                elif check_type == "field_required":
                    actual = bool(field.Required) if field else False
                    passed = actual == (wanted.casefold() in {"true", "yes", "1"})
                elif check_type == "field_default":
                    actual = str(getattr(field, "DefaultValue", "") or "").strip("\"'") if field else ""
                    passed = _normalise(actual) == _normalise(wanted)
                elif check_type == "field_validation_rule":
                    actual = str(getattr(field, "ValidationRule", "") or "") if field else ""
                    passed = _normalise(wanted) in _normalise(actual)
                elif check_type == "field_validation_text":
                    actual = str(getattr(field, "ValidationText", "") or "") if field else ""
                    passed = _normalise(wanted) in _normalise(actual)
                elif check_type == "field_input_mask":
                    actual = str(_property_value(field, "InputMask", "") or "")
                    passed = _normalise(wanted) in _normalise(actual)
                elif check_type == "field_format":
                    actual = str(_property_value(field, "Format", "") or "")
                    passed = _normalise(wanted) in _normalise(actual)
                elif check_type == "field_lookup_values":
                    actual = str(_property_value(field, "RowSource", "") or "")
                    values = [part.strip().casefold() for part in wanted.split(",") if part.strip()]
                    passed = all(value in actual.casefold() for value in values)
                elif check_type in {"field_lookup_present", "field_lookup_type"}:
                    row_source = str(_property_value(field, "RowSource", "") or "")
                    row_source_type = _normalise(_property_value(field, "RowSourceType", ""))
                    display_control = _property_value(field, "DisplayControl")
                    actual = {"row_source": row_source, "row_source_type": row_source_type, "display_control": display_control}
                    has_lookup = bool(row_source) or row_source_type in {"value list", "table/query", "field list"} or display_control in {110, 111}
                    if check_type == "field_lookup_present":
                        passed = has_lookup
                    else:
                        aliases = {"combo": "combo box", "combobox": "combo box", "value-list": "value list"}
                        expected_type = aliases.get(_normalise(wanted), _normalise(wanted))
                        passed = expected_type in row_source_type or (
                            expected_type in {"combo", "combo box"} and display_control == 111
                        )
                elif check_type == "field_display_control":
                    actual = _property_value(field, "DisplayControl")
                    try: actual = int(actual)
                    except (TypeError, ValueError): actual = None
                    passed = (wanted.casefold() in {"combo", "combo box"} and actual == 111) or str(actual) == wanted
            elif check_type == "primary_key":
                table = tables.get(table_name.casefold())
                names = []
                if table:
                    for index in range(table.Indexes.Count):
                        item = table.Indexes(index)
                        if bool(item.Primary): names.extend(str(item.Fields(pos).Name) for pos in range(item.Fields.Count))
                actual = names
                passed = wanted.casefold() in {name.casefold() for name in names}
            elif check_type in {
                "query_exists", "query_sql_contains", "query_source_contains", "query_fields",
                "query_criteria_contains", "query_group_by", "query_aggregate", "query_sort_order",
            }:
                queries = {str(db.QueryDefs(index).Name).casefold(): str(db.QueryDefs(index).SQL) for index in range(db.QueryDefs.Count) if not str(db.QueryDefs(index).Name).startswith("~")}
                query_name = str((target or {}).get("query", ""))
                if check_type == "query_exists":
                    actual = list(queries)
                    passed = wanted.casefold() in queries
                else:
                    actual = queries.get(query_name.casefold(), "")
                    normal_sql = _normalise(actual)
                    if check_type in {"query_sql_contains", "query_criteria_contains"}:
                        passed = _normalise(wanted) in normal_sql
                    elif check_type == "query_source_contains":
                        passed = f"from {_normalise(wanted)}" in normal_sql or _normalise(wanted) in normal_sql
                    elif check_type == "query_fields":
                        passed = all(token in normal_sql for token in _sql_tokens(wanted))
                    elif check_type == "query_group_by":
                        passed = "group by" in normal_sql and all(token in normal_sql for token in _sql_tokens(wanted))
                    elif check_type == "query_aggregate":
                        # Example expected value: "sum:Credit Balance" or "max:Age".
                        function, _, field = wanted.partition(":")
                        passed = f"{_normalise(function)}(" in normal_sql and (not field or _normalise(field) in normal_sql)
                    elif check_type == "query_sort_order":
                        passed = "order by" in normal_sql and _normalise(wanted) in normal_sql
            elif check_type.startswith("form_") or check_type.startswith("report_"):
                application = win32.DispatchEx("Access.Application")
                application.Visible = False
                try:
                    application.OpenCurrentDatabase(str(file_path.resolve()))
                    collection = application.CurrentProject.AllForms if check_type.startswith("form_") else application.CurrentProject.AllReports
                    object_name = str((target or {}).get("object", ""))
                    names = [str(collection.Item(index).Name) for index in range(collection.Count)]
                    object_type = 2 if check_type.startswith("form_") else 3
                    if check_type in {"form_exists", "report_exists"}:
                        actual = names
                        passed = wanted.casefold() in {name.casefold() for name in names}
                    else:
                        name = object_name or (names[0] if names else "")
                        application.DoCmd.OpenForm(name, 1) if object_type == 2 else application.DoCmd.OpenReport(name, 1)
                        obj = application.Forms(name) if object_type == 2 else application.Reports(name)
                        controls = [obj.Controls(index) for index in range(obj.Controls.Count)]
                        sources = [str(getattr(control, "ControlSource", "") or "") for control in controls]
                        captions = [str(getattr(control, "Caption", "") or "") for control in controls]
                        if check_type in {"form_control_source", "report_control_source"}:
                            actual = sources
                            passed = _normalise(wanted) in {_normalise(value) for value in sources}
                        elif check_type in {"form_caption_contains", "report_caption_contains"}:
                            actual = captions
                            passed = any(_normalise(wanted) in _normalise(value) for value in captions)
                        elif check_type == "form_image_contains":
                            actual = [str(getattr(control, "Picture", "") or "") for control in controls]
                            passed = any(_normalise(wanted) in _normalise(value) for value in actual)
                        elif check_type == "form_caption_style":
                            # Expected: "caption text|center|underline". Style portions are optional.
                            parts = [part.strip() for part in wanted.split("|")]
                            caption_text = parts[0] if parts else ""
                            matching = [control for control in controls if _normalise(caption_text) in _normalise(getattr(control, "Caption", ""))]
                            actual = [(getattr(control, "TextAlign", None), bool(getattr(control, "FontUnderline", False))) for control in matching]
                            wants_center = len(parts) > 1 and parts[1].casefold() == "center"
                            wants_underline = len(parts) > 2 and parts[2].casefold() == "underline"
                            passed = bool(matching) and any((not wants_center or getattr(control, "TextAlign", None) in {2, 3}) and (not wants_underline or bool(getattr(control, "FontUnderline", False))) for control in matching)
                        elif check_type == "form_expression_contains":
                            actual = sources
                            passed = any(_normalise(wanted) in _normalise(value) for value in sources)
                        elif check_type == "form_record_source":
                            actual = str(getattr(obj, "RecordSource", "") or "")
                            passed = _normalise(wanted) == _normalise(actual)
                        elif check_type in {"form_footer_control_source", "form_footer_expression_contains"}:
                            footer_sources = [
                                str(getattr(control, "ControlSource", "") or "")
                                for control in controls if getattr(control, "Section", None) == 2
                            ]
                            actual = footer_sources
                            if check_type == "form_footer_control_source":
                                passed = _normalise(wanted) in {_normalise(value) for value in footer_sources}
                            else:
                                passed = any(_normalise(wanted) in _normalise(value) for value in footer_sources)
                        elif check_type == "form_control_order":
                            expected_fields = _sql_tokens(wanted)
                            actual = [_normalise(value) for value in sources]
                            indexes = [actual.index(name) if name in actual else -1 for name in expected_fields]
                            passed = all(index >= 0 for index in indexes) and indexes == sorted(indexes)
                        elif check_type == "report_record_source":
                            actual = str(getattr(obj, "RecordSource", "") or "")
                            passed = _normalise(wanted) == _normalise(actual)
                        elif check_type == "report_group_control":
                            matching = [control for control in controls if _normalise(getattr(control, "ControlSource", "")) == _normalise(wanted)]
                            actual = [getattr(control, "Section", None) for control in matching]
                            passed = any(section in {5, 6, 7, 8} for section in actual)
                        elif check_type == "report_control_order":
                            expected_fields = _sql_tokens(wanted)
                            actual = [_normalise(value) for value in sources]
                            indexes = [actual.index(name) if name in actual else -1 for name in expected_fields]
                            passed = all(index >= 0 for index in indexes) and indexes == sorted(indexes)
                        elif check_type == "report_expression_contains":
                            actual = sources
                            passed = any(_normalise(wanted) in _normalise(value) for value in sources)
                        elif check_type == "report_group_order":
                            expected_fields = _sql_tokens(wanted)
                            actual = []
                            for field in expected_fields:
                                sections = [
                                    int(getattr(control, "Section", -1)) for control in controls
                                    if _normalise(getattr(control, "ControlSource", "")) == field
                                    and getattr(control, "Section", None) in {5, 6, 7, 8}
                                ]
                                actual.append(min(sections) if sections else None)
                            passed = all(section is not None for section in actual) and actual == sorted(actual)
                finally:
                    try: application.CloseCurrentDatabase()
                    except Exception: pass
                    application.Quit()
            return CheckerResult(passed, actual, {"type": check_type, "target": target, "expected": expected})
        except Exception as exc:
            return CheckerResult(False, details={"reason": f"Access inspection failed: {exc}"})
        finally:
            if db is not None:
                try: db.Close()
                except Exception: pass
            pythoncom.CoUninitialize()
