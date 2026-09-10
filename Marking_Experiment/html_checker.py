"""Reusable checks for no-code HTML practical tasks."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List

from .checker_types import BaseChecker, CheckerResult


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _colour(value: Any) -> str:
    value = str(value or "").strip().casefold()
    value = value.replace("#", "")
    names = {"yellow": "ffff00", "green": "008000", "brown": "a52a2a", "white": "ffffff", "black": "000000"}
    return names.get(value, value)


class _Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: List[Dict[str, Any]] = []
        self.stack: List[Dict[str, Any]] = []
        self.comments: List[str] = []
        self.errors: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        element = {"tag": tag.casefold(), "attrs": {k.casefold(): v or "" for k, v in attrs}, "text": ""}
        self.elements.append(element)
        if tag.casefold() not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1]["tag"] == tag.casefold():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        for pos in range(len(self.stack) - 1, -1, -1):
            if self.stack[pos]["tag"] == tag:
                del self.stack[pos:]
                return
        self.errors.append(f"Unexpected closing tag: {tag}")

    def handle_data(self, data: str) -> None:
        for element in self.stack:
            element["text"] += data

    def handle_comment(self, data: str) -> None:
        self.comments.append(data)


class HTMLChecker(BaseChecker):
    program = "html"

    def _document(self, file_path: Path) -> tuple[str, _Document]:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        document = _Document()
        document.feed(source)
        document.close()
        return source, document

    @staticmethod
    def _elements(document: _Document, tag: str = "", text: str = "") -> List[Dict[str, Any]]:
        required_text = _normalise(text)
        return [element for element in document.elements if (not tag or element["tag"] == tag.casefold()) and (not required_text or required_text in _normalise(element["text"]))]

    def check(self, domain: str, check_type: str, target: Dict[str, Any], expected: Any, file_path: Path) -> CheckerResult:
        try:
            source, document = self._document(file_path)
        except Exception as exc:
            return CheckerResult(False, details={"reason": f"Could not read HTML: {exc}"})

        expected_text = str(expected or "")
        tag = str((target or {}).get("tag", ""))
        text = str((target or {}).get("text", ""))
        elements = self._elements(document, tag, text)
        passed = False
        actual: Any = None

        if check_type == "document_structure":
            passed = bool(re.search(r"<!doctype\s+html", source, re.I) and re.search(r"<html\b", source, re.I) and re.search(r"</html\s*>", source, re.I) and not document.stack and not document.errors)
            actual = "valid structure" if passed else "missing document tags or unmatched tags"
        elif check_type == "document_title":
            titles = self._elements(document, "title")
            actual = [item["text"] for item in titles]
            passed = any(_normalise(expected_text) == _normalise(item["text"]) for item in titles)
        elif check_type == "element_text":
            if not text:
                elements = self._elements(document, tag, expected_text)
            actual = [item["text"] for item in elements]
            passed = bool(elements)
        elif check_type == "element_has_child_tag":
            child_tag = expected_text.casefold()
            actual = [item["text"] for item in elements]
            # Match nested markup from the submitted source while retaining the selected parent text.
            parent_pattern = rf"<{re.escape(tag)}\\b[^>]*>[\\s\\S]*?<{re.escape(child_tag)}\\b"
            if text:
                parent_pattern = rf"<{re.escape(tag)}\\b[^>]*>[\\s\\S]*?{re.escape(text)}[\\s\\S]*?<{re.escape(child_tag)}\\b|<{re.escape(tag)}\\b[^>]*>[\\s\\S]*?<{re.escape(child_tag)}\\b[\\s\\S]*?{re.escape(text)}"
            passed = bool(re.search(parent_pattern, source, re.I))
        elif check_type == "element_attribute":
            attribute = str((expected if isinstance(expected, dict) else {}).get("attribute", "")).casefold()
            value = str((expected if isinstance(expected, dict) else {}).get("value", ""))
            actual = [item["attrs"].get(attribute, "") for item in elements]
            passed = any(_normalise(value) == _normalise(item["attrs"].get(attribute, "")) for item in elements)
        elif check_type == "body_background_color":
            bodies = self._elements(document, "body")
            wanted = _colour(expected_text)
            actual = [item["attrs"].get("bgcolor", "") for item in bodies]
            passed = any(_colour(value) == wanted for value in actual)
        elif check_type == "html_comment_contains":
            actual = document.comments
            passed = any(_normalise(expected_text) in _normalise(comment) for comment in document.comments)
        elif check_type == "list_exists":
            actual = len(self._elements(document, expected_text))
            passed = actual > 0
        elif check_type == "list_item_contains":
            actual = [item["text"] for item in self._elements(document, "li")]
            passed = any(_normalise(expected_text) in _normalise(value) for value in actual)
        elif check_type == "list_minimum_items":
            list_tag = str((target or {}).get("tag", "ul"))
            # A practical rubric only needs the count in the requested list type.
            count = len(self._elements(document, "li")) if self._elements(document, list_tag) else 0
            actual = count
            passed = count >= int(expected)
        elif check_type == "horizontal_rule":
            attribute = str((target or {}).get("attribute", ""))
            hrs = self._elements(document, "hr")
            actual = [item["attrs"] for item in hrs]
            passed = bool(hrs) if not attribute else any(_normalise(item["attrs"].get(attribute, "")) == _normalise(expected_text) for item in hrs)
        elif check_type == "line_break":
            actual = len(self._elements(document, "br"))
            passed = actual > 0
        elif check_type == "link_href":
            links = self._elements(document, "a", text)
            actual = [item["attrs"].get("href", "") for item in links]
            passed = any(_normalise(expected_text) in _normalise(value) for value in actual)
        elif check_type == "link_present":
            actual = len(self._elements(document, "a"))
            passed = actual > 0
        elif check_type == "link_text":
            actual = [item["text"] for item in self._elements(document, "a")]
            passed = any(_normalise(expected_text) == _normalise(value) for value in actual)
        elif check_type == "image_src":
            actual = [item["attrs"].get("src", "") for item in self._elements(document, "img")]
            passed = any(_normalise(expected_text) in _normalise(value) for value in actual)
        elif check_type == "image_alt":
            actual = [item["attrs"].get("alt", "") for item in self._elements(document, "img")]
            passed = any(_normalise(expected_text) in _normalise(value) for value in actual)
        elif check_type == "table_cell_text":
            cells = self._elements(document, "td") + self._elements(document, "th")
            actual = [item["text"] for item in cells]
            passed = any(_normalise(expected_text) == _normalise(value) for value in actual)

        return CheckerResult(passed=passed, actual=actual, details={"type": check_type, "target": target, "expected": expected})
