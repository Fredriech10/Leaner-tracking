import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List


@dataclass
class CheckResult:
    status: str
    awarded: int | float | str
    reason: str


class SimpleHTMLAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.comments: List[str] = []
        self.start_tags: List[tuple[str, Dict[str, str]]] = []
        self.end_tags: List[str] = []
        self.text_parts: List[str] = []
        self.title_text = ""
        self._in_title = False
        self.parse_error = ""

    def handle_comment(self, data: str) -> None:
        self.comments.append(data.strip())

    def handle_starttag(self, tag: str, attrs) -> None:
        attr_map = {k.lower(): (v if v is not None else "") for k, v in attrs}
        self.start_tags.append((tag.lower(), attr_map))
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        self.end_tags.append(tag.lower())
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_text += data
        self.text_parts.append(data)

    def error(self, message: str) -> None:  # pragma: no cover
        self.parse_error = message


class Q6Document:
    def __init__(self, path: Path):
        self.path = path
        self.exists = path.exists()
        self.errors: List[str] = []
        self.text = ""
        self.normalized_text = ""
        self.parser = SimpleHTMLAudit()

        self.comment_has_name = False
        self.title_ok = False
        self.body_bg_ok = False
        self.center_ok = False
        self.ul_square_ok = False
        self.h3_ok = False
        self.ol_type_a_ok = False
        self.ol_start_4_ok = False
        self.bounce_row_present = False
        self.bounce_content_ok = False
        self.href_present = False
        self.href_target = ""
        self.href_q6_2_html = False
        self.nesting_ok = False

        if self.exists:
            try:
                self._load()
            except Exception as exc:  # pragma: no cover
                self.errors.append(f"Q6 parse error: {exc}")
        else:
            self.errors.append("Q6 file not found")

    def _load(self) -> None:
        self.text = self.path.read_text(encoding="utf-8", errors="ignore")
        self.normalized_text = re.sub(r"\s+", " ", self.text)
        self.parser.feed(self.text)
        self._evaluate()

    def _evaluate(self) -> None:
        self.comment_has_name = any(
            "question 6.1.1" not in c.lower() and len(c.split()) >= 2
            for c in self.parser.comments
        )
        self.title_ok = self._norm(self.parser.title_text) == "essentials of digital marketing"

        for tag, attrs in self.parser.start_tags:
            if tag == "body" and self._norm(attrs.get("bgcolor", "")) == "#f5f5f5":
                self.body_bg_ok = True
            if tag == "p" and self._norm(attrs.get("align", "")) == "center":
                self.center_ok = True
            if tag == "ul" and self._norm(attrs.get("type", "")) == "square":
                self.ul_square_ok = True
            if tag == "ol":
                if self._norm(attrs.get("type", "")) == "a":
                    self.ol_type_a_ok = True
                if self._norm(attrs.get("start", "")) == "4":
                    self.ol_start_4_ok = True
            if tag == "a":
                href = attrs.get("href", "")
                if href:
                    self.href_present = True
                    self.href_target = href
                    if href.lower().endswith("q6_2.html"):
                        self.href_q6_2_html = True

        self.h3_ok = bool(re.search(r"<h3>\s*Why it matters\s*</h3>", self.text, re.I))

        bounce_term = re.search(r"<td>\s*Bounce rate\s*</td>", self.text, re.I)
        bounce_desc = re.search(
            r"<td>\s*The percentage of visitors who leave a website without interacting further\.?\s*</td>",
            self.text,
            re.I,
        )
        self.bounce_row_present = bool(bounce_term and bounce_desc)
        self.bounce_content_ok = self.bounce_row_present

        self.nesting_ok = (
            self.text.lower().count("<html") == 1
            and self.text.lower().count("<body") == 1
            and self.text.lower().count("</html>") >= 1
            and self.text.lower().count("</body>") >= 1
            and self.text.lower().count("<a") == self.text.lower().count("</a>")
            and self.text.lower().count("<ol") == self.text.lower().count("</ol>")
            and self.text.lower().count("<ul") == self.text.lower().count("</ul>")
            and self.text.lower().count("<table") == self.text.lower().count("</table>")
        )

    def _norm(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())


def evaluate_q6_check(doc: Q6Document, check: Dict) -> CheckResult:
    if not doc.exists:
        return CheckResult("manual", "", "Q6 file missing")
    if doc.errors:
        return CheckResult("manual", "", "; ".join(doc.errors))

    desc = check["description"]
    mark = check["mark"]

    def pass_fail(ok: bool, ok_reason: str, fail_reason: str) -> CheckResult:
        return CheckResult("pass" if ok else "fail", mark if ok else 0, ok_reason if ok else fail_reason)

    mapping = {
        "comment": lambda: pass_fail(doc.comment_has_name, "Learner comment detected", "Learner comment not detected"),
        "<!-- Name and Surname-->": lambda: pass_fail(doc.comment_has_name, "Learner comment detected", "Learner comment not detected"),
        "title tag": lambda: pass_fail(bool(doc.parser.title_text.strip()), "Title tag text detected", "Title tag text not detected"),
        "<title>Essentials of Digital Marketing</title>": lambda: pass_fail(
            doc.title_ok,
            "Title matches Essentials of Digital Marketing",
            f"Title text is {doc.parser.title_text!r}",
        ),
        "page colour": lambda: pass_fail(doc.body_bg_ok, "Body background colour detected", "Body background colour not detected"),
        '<body bgcolor="#F5F5F5">': lambda: pass_fail(
            doc.body_bg_ok,
            "Body background colour is #F5F5F5",
            "Body background colour #F5F5F5 not detected",
        ),
        "alignment": lambda: pass_fail(doc.center_ok, "Centered first paragraph detected", "Centered first paragraph not detected"),
        "<centre></centre>": lambda: pass_fail(doc.center_ok, "Centered first paragraph detected", "Centered first paragraph not detected"),
        "bulleted list": lambda: pass_fail(doc.ul_square_ok, "Square bulleted list detected", "Square bulleted list not detected"),
        "<type": lambda: pass_fail(doc.ul_square_ok, "List type attribute detected", "List type attribute not detected"),
        '=”square”>': lambda: pass_fail(doc.ul_square_ok, 'List type is square', 'List type square not detected'),
        "heading": lambda: pass_fail(doc.h3_ok, "H3 Why it matters detected", "H3 Why it matters not detected"),
        "<h3>Why it matters</h3>": lambda: pass_fail(doc.h3_ok, "H3 Why it matters detected", "H3 Why it matters not detected"),
        "list to display as": lambda: pass_fail(doc.ol_type_a_ok, "Ordered list type A detected", "Ordered list type A not detected"),
        '<ol type="A"   >': lambda: pass_fail(doc.ol_type_a_ok, "Ordered list type A detected", "Ordered list type A not detected"),
        'start="4"': lambda: pass_fail(doc.ol_start_4_ok, 'Ordered list start="4" detected', 'Ordered list start="4" not detected'),
        "table formatting": lambda: pass_fail(doc.bounce_row_present, "Bounce rate table row detected", "Bounce rate table row not detected"),
        "": lambda: pass_fail(doc.bounce_row_present, "Bounce rate table row detected", "Bounce rate table row not detected"),
        "columns: <td>Bounce rate</td>; <td>The percentage of visitors who leave a website without interacting further. </td>": lambda: pass_fail(
            doc.bounce_row_present,
            "Bounce rate row content detected",
            "Bounce rate row content not detected",
        ),
        "correct content": lambda: pass_fail(doc.bounce_content_ok, "Bounce rate row content detected", "Bounce rate row content not detected"),
        "hyperlink": lambda: pass_fail(doc.href_present, "Hyperlink href detected", "Hyperlink href not detected"),
        "added href": lambda: pass_fail(doc.href_present, "Hyperlink href detected", "Hyperlink href not detected"),
        "correct file name: Q6_2.html": lambda: pass_fail(
            doc.href_q6_2_html,
            "Hyperlink points to Q6_2.html",
            f"Hyperlink target is {doc.href_target!r}",
        ),
        "ONE mark will be allocated for closing tags and correct nesting in both the web pages.": lambda: pass_fail(
            doc.nesting_ok,
            "Basic closing tags and nesting checks passed",
            "Closing tags or nesting checks failed",
        ),
    }

    if desc in mapping:
        return mapping[desc]()
    return CheckResult("manual", "", f"Q6 actual checker not implemented for {desc}")
