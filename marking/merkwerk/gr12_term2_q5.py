import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import win32com.client as win32


@dataclass
class CheckResult:
    status: str
    awarded: int | float | str
    reason: str


def normalize_sql(value: str) -> str:
    value = (value or "").replace("\r", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


class Q5Database:
    def __init__(self, path: Path):
        self.path = path
        self.exists = path.exists()
        self.errors: List[str] = []

        self.tables: Dict[str, Dict] = {}
        self.queries: Dict[str, str] = {}
        self.reports: Dict[str, Dict] = {}

        if self.exists:
            try:
                self._load()
            except Exception as exc:  # pragma: no cover
                self.errors.append(f"Q5 parse error: {exc}")
        else:
            self.errors.append("Q5 database file not found")

    def _load(self) -> None:
        acc = win32.DispatchEx("Access.Application")
        try:
            acc.OpenCurrentDatabase(str(self.path.resolve()))
            db = acc.CurrentDb()
            self._load_tables(db)
            self._load_queries(db)
            self._load_reports(acc)
            acc.CloseCurrentDatabase()
        finally:
            acc.Quit()

    def _load_tables(self, db) -> None:
        for table_def in db.TableDefs:
            name = table_def.Name
            if str(name).startswith("MSys"):
                continue
            fields = {}
            for field in table_def.Fields:
                props = {}
                for key in ["Type", "Size", "Required", "DefaultValue", "ValidationRule", "ValidationText"]:
                    try:
                        props[key] = getattr(field, key)
                    except Exception:
                        props[key] = None
                for prop in field.Properties:
                    if prop.Name in {"Format", "InputMask", "DisplayControl", "RowSourceType", "RowSource"}:
                        props[prop.Name] = prop.Value
                fields[field.Name.lower()] = props
            self.tables[name.lower()] = {"name": name, "fields": fields}

    def _load_queries(self, db) -> None:
        for query in db.QueryDefs:
            name = query.Name
            if str(name).startswith("~"):
                continue
            self.queries[name.lower()] = query.SQL

    def _load_reports(self, acc) -> None:
        for report_doc in acc.CurrentProject.AllReports:
            name = report_doc.Name
            try:
                acc.DoCmd.OpenReport(name, 1)
                report = acc.Reports(name)
                controls = []
                for i in range(report.Controls.Count):
                    control = report.Controls(i)
                    try:
                        controls.append(
                            {
                                "name": control.Name,
                                "type": control.ControlType,
                                "source": getattr(control, "ControlSource", ""),
                                "section": getattr(control, "Section", None),
                            }
                        )
                    except Exception:
                        pass
                self.reports[name.lower()] = {
                    "name": name,
                    "record_source": getattr(report, "RecordSource", ""),
                    "controls": controls,
                }
            finally:
                try:
                    acc.DoCmd.Close(3, name, 0)
                except Exception:
                    pass


def evaluate_q5_check(doc: Q5Database, check: Dict) -> CheckResult:
    if not doc.exists:
        return CheckResult("fail", 0 if check["mark"] else "", "Q5 database file missing")
    if doc.errors:
        return CheckResult("manual", "", "; ".join(doc.errors))

    desc = check["description"]
    mark = check["mark"]
    tbl = doc.tables.get("tbl5_1", {}).get("fields", {})
    tblx = doc.tables.get("tbl5_1 (xtra)", {}).get("fields", {})

    campaign_type = tbl.get("campaigntype", {})
    convert = tbl.get("convert", {})
    gender = tbl.get("gender", {})
    purchases = tbl.get("purchases", {})
    age = tbl.get("age", {})
    income = tbl.get("income", {})

    def pass_fail(ok: bool, ok_reason: str, fail_reason: str) -> CheckResult:
        return CheckResult("pass" if ok else "fail", mark if ok else 0, ok_reason if ok else fail_reason)

    def qsql(name: str) -> str:
        return normalize_sql(doc.queries.get(name.lower(), ""))

    def has_fields(sql: str, fields: List[str]) -> bool:
        return all(field.lower() in sql for field in fields)

    def query_exists(name: str) -> bool:
        return name.lower() in doc.queries

    qry52 = qsql("qry5_2")
    qry53 = qsql("qry5_3")
    qry54 = qsql("qry5_4")
    qry55 = qsql("qry5_5")
    group_sections = {5, 6, 7, 8}

    def report_sources(report: Dict) -> List[str]:
        return [str(c.get("source", "")) for c in report.get("controls", [])]

    def control_in_group_section(report: Dict, field_name: str) -> bool:
        for control in report.get("controls", []):
            if str(control.get("source", "")).strip().lower() == field_name.lower() and control.get("section") in group_sections:
                return True
        return False

    def report_matches(report: Dict, predicate) -> bool:
        try:
            return predicate(report)
        except Exception:
            return False

    def any_report_matches(predicate) -> bool:
        return any(report_matches(report, predicate) for report in doc.reports.values())

    def first_report_reason(predicate, success_reason: str, fail_prefix: str) -> CheckResult:
        for report in doc.reports.values():
            if report_matches(report, predicate):
                return CheckResult("pass", mark, f"{success_reason}: {report.get('name')}")
        if not doc.reports:
            return CheckResult("fail", 0, f"{fail_prefix}: no reports found")
        report_names = ", ".join(sorted(report.get("name", "") for report in doc.reports.values()))
        return CheckResult("fail", 0, f"{fail_prefix}: checked reports {report_names}")

    row_source = str(campaign_type.get("RowSource", "") or "")
    row_source_norm = normalize_sql(row_source.replace(";", " ; "))
    input_mask = str(income.get("InputMask", "") or "")
    row_source_type = str(campaign_type.get("RowSourceType", "") or "").lower()
    display_control = campaign_type.get("DisplayControl")

    def lookup_style_present() -> bool:
        if row_source_type == "value list":
            return True
        if display_control in {110, 111}:
            return True
        if row_source and (";" in row_source or row_source_type in {"table/query", "field list"}):
            return True
        return False

    mapping = {
        "field size of the CampaignType field set at 15": lambda: pass_fail(
            campaign_type.get("Size") == 15,
            "CampaignType field size is 15",
            f"CampaignType field size is {campaign_type.get('Size')!r}",
        ),
        "Convert field to Yes/No data type": lambda: pass_fail(
            convert.get("Type") == 1 or str(convert.get("Format", "")).lower() == "yes/no",
            "Convert field is Yes/No",
            f"Convert field type/format are {convert.get('Type')!r} / {convert.get('Format')!r}",
        ),
        "validation": lambda: pass_fail(
            bool(gender.get("ValidationRule")) and bool(gender.get("ValidationText")),
            "Gender validation rule and text detected",
            "Gender validation rule/text not fully detected",
        ),
        'validation rule contains "Male"': lambda: pass_fail(
            "male" in normalize_sql(str(gender.get("ValidationRule", ""))),
            'Gender validation rule references "Male"',
            f"Gender validation rule is {gender.get('ValidationRule')!r}",
        ),
        'validation rule contains "Female"': lambda: pass_fail(
            "female" in normalize_sql(str(gender.get("ValidationRule", ""))),
            'Gender validation rule references "Female"',
            f"Gender validation rule is {gender.get('ValidationRule')!r}",
        ),
        'validation text contains "Male"': lambda: pass_fail(
            "male" in normalize_sql(str(gender.get("ValidationText", ""))),
            'Gender validation text references "Male"',
            f"Gender validation text is {gender.get('ValidationText')!r}",
        ),
        'validation text contains "Female"': lambda: pass_fail(
            "female" in normalize_sql(str(gender.get("ValidationText", ""))),
            'Gender validation text references "Female"',
            f"Gender validation text is {gender.get('ValidationText')!r}",
        ),
        "value 9 entered": lambda: pass_fail(
            str(purchases.get("DefaultValue", "")).strip().strip('"') == "9",
            "Purchases default value is 9",
            f"Purchases default value is {purchases.get('DefaultValue')!r}",
        ),
        "Age field set at Required , yes": lambda: pass_fail(
            bool(age.get("Required")),
            "Age field is required",
            f"Age field Required is {age.get('Required')!r}",
        ),
        "Currency symbol": lambda: pass_fail(
            "R" in input_mask or "R" in str(income.get("Format", "") or ""),
            "Income currency symbol detected",
            f"Income input mask/format are {input_mask!r} / {income.get('Format')!r}",
        ),
        "9 → Optional digit": lambda: pass_fail(
            "#" in input_mask or "9" in input_mask,
            "Income input mask has optional digit pattern",
            f"Income input mask is {input_mask!r}",
        ),
        ".99 → Two decimal places": lambda: pass_fail(
            ".00" in input_mask or ".99" in input_mask or ".00" in str(income.get("Format", "") or ""),
            "Income input mask/format has two decimal places",
            f"Income input mask/format are {input_mask!r} / {income.get('Format')!r}",
        ),
        "Data type as Lookup value": lambda: pass_fail(
            lookup_style_present(),
            "CampaignType is clearly configured as a lookup/combo-style field",
            f"CampaignType RowSourceType/DisplayControl/RowSource are {campaign_type.get('RowSourceType')!r} / {campaign_type.get('DisplayControl')!r} / {row_source!r}",
        ),
        "Display control is a Combo Box": lambda: pass_fail(
            campaign_type.get("DisplayControl") == 111,
            "CampaignType display control is Combo Box",
            f"CampaignType DisplayControl is {campaign_type.get('DisplayControl')!r}",
        ),
        "Value list, with indicated values": lambda: pass_fail(
            all(token in row_source_norm for token in ["awareness", "consideration", "conversion", "retention"]),
            "CampaignType value list contains the indicated values",
            f"CampaignType RowSource is {row_source!r}",
        ),
        "customers “Female”": lambda: pass_fail(
            query_exists("qry5_2") and "female" in qry52,
            "qry5_2 filters Female customers",
            f"qry5_2 SQL is {doc.queries.get('qry5_2','')!r}",
        ),
        "income < R100000.00": lambda: pass_fail(
            query_exists("qry5_2") and ("<100000" in qry52 or "<=100000" in qry52),
            "qry5_2 filters income below 100000",
            f"qry5_2 SQL is {doc.queries.get('qry5_2','')!r}",
        ),
        "fields CustomerID, Age, Gender and Income": lambda: pass_fail(
            query_exists("qry5_2") and has_fields(qry52, ["customerid", "age", "gender", "income"]),
            "qry5_2 includes CustomerID, Age, Gender and Income",
            f"qry5_2 SQL is {doc.queries.get('qry5_2','')!r}",
        ),
        "query called qry5_3 based on the tbl5_1 table": lambda: pass_fail(
            query_exists("qry5_3") and "from tbl5_1" in qry53,
            "qry5_3 exists and uses tbl5_1",
            f"qry5_3 SQL is {doc.queries.get('qry5_3','')!r}",
        ),
        "age > 40": lambda: pass_fail(
            query_exists("qry5_3") and ">40" in qry53,
            "qry5_3 filters age > 40",
            f"qry5_3 SQL is {doc.queries.get('qry5_3','')!r}",
        ),
        "Purchses = 4": lambda: pass_fail(
            query_exists("qry5_3") and "purchases" in qry53 and "=4" in qry53,
            "qry5_3 filters Purchases = 4",
            f"qry5_3 SQL is {doc.queries.get('qry5_3','')!r}",
        ),
        "CampaignChannel “Email": lambda: pass_fail(
            query_exists("qry5_3") and "campaignchannel" in qry53 and "email" in qry53,
            "qry5_3 filters CampaignChannel Email",
            f"qry5_3 SQL is {doc.queries.get('qry5_3','')!r}",
        ),
        "The fields CustomerID, Age, CampaignChannel and Purchases": lambda: pass_fail(
            query_exists("qry5_3") and has_fields(qry53, ["customerid", "age", "campaignchannel", "purchases"]),
            "qry5_3 includes CustomerID, Age, CampaignChannel and Purchases",
            f"qry5_3 SQL is {doc.queries.get('qry5_3','')!r}",
        ),
        "query called qry5_4 based on the tbl5_1 (Xtra) table as follows": lambda: pass_fail(
            query_exists("qry5_4") and "tbl5_1 (xtra)" in qry54,
            "qry5_4 exists and uses tbl5_1 (Xtra)",
            f"qry5_4 SQL is {doc.queries.get('qry5_4','')!r}",
        ),
        "country = “USA”": lambda: pass_fail(
            query_exists("qry5_4") and "country" in qry54 and "usa" in qry54,
            "qry5_4 filters Country USA",
            f"qry5_4 SQL is {doc.queries.get('qry5_4','')!r}",
        ),
        "Credit Balance is Null": lambda: pass_fail(
            query_exists("qry5_4") and "credit balance" in qry54 and "is null" in qry54,
            "qry5_4 filters Credit Balance Is Null",
            f"qry5_4 SQL is {doc.queries.get('qry5_4','')!r}",
        ),
        "show the fields Age, Gender and Country": lambda: pass_fail(
            query_exists("qry5_4") and has_fields(qry54, ["age", "gender", "country"]),
            "qry5_4 includes Age, Gender and Country",
            f"qry5_4 SQL is {doc.queries.get('qry5_4','')!r}",
        ),
        "query called qry5_5 based on the tbl5_1 (Xtra) table": lambda: pass_fail(
            query_exists("qry5_5") and "tbl5_1 (xtra)" in qry55,
            "qry5_5 exists and uses tbl5_1 (Xtra)",
            f"qry5_5 SQL is {doc.queries.get('qry5_5','')!r}",
        ),
        "Grouped by Country": lambda: pass_fail(
            query_exists("qry5_5") and "group by" in qry55 and "country" in qry55,
            "qry5_5 groups by Country",
            f"qry5_5 SQL is {doc.queries.get('qry5_5','')!r}",
        ),
        "Sum of Credit Balance": lambda: pass_fail(
            query_exists("qry5_5") and "sum(" in qry55 and "credit balance" in qry55,
            "qry5_5 sums Credit Balance",
            f"qry5_5 SQL is {doc.queries.get('qry5_5','')!r}",
        ),
        "MAX Oldest person": lambda: pass_fail(
            query_exists("qry5_5") and "max(" in qry55 and "age" in qry55,
            "qry5_5 uses MAX on Age",
            f"qry5_5 SQL is {doc.queries.get('qry5_5','')!r}",
        ),
        "rpt5_6 report, based on the tbl5_1 table": lambda: first_report_reason(
            lambda report: normalize_sql(str(report.get("record_source", ""))) == "tbl5_1",
            "Report based on tbl5_1",
            "No report based on tbl5_1",
        ),
        "fields Age, Gender, Income, CampaignChannel.": lambda: first_report_reason(
            lambda report: all(field in report_sources(report) for field in ["Age", "Gender", "Income", "CampaignChannel"]),
            "Report contains Age, Gender, Income and CampaignChannel controls",
            "No report contains all required field controls",
        ),
        "Group the records by CampaignChannel": lambda: first_report_reason(
            lambda report: control_in_group_section(report, "CampaignChannel"),
            "Report groups by CampaignChannel",
            "No report shows CampaignChannel in a group section",
        ),
        "then Gender": lambda: first_report_reason(
            lambda report: control_in_group_section(report, "Gender"),
            "Report groups by Gender",
            "No report shows Gender in a group section",
        ),
        "Summary Grand Total = =Sum([Income])": lambda: first_report_reason(
            lambda report: any("sum([income])" in normalize_sql(src) for src in report_sources(report)),
            "Report contains Sum([Income]) summary control",
            "No report contains Sum([Income]) summary control",
        ),
    }

    if desc in mapping:
        return mapping[desc]()
    return CheckResult("manual", "", f"Q5 actual checker not implemented for {desc}")
