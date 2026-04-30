"""
checkers/html.py
Reusable check functions for HTML (.html) assignments.
All functions take filepath as first argument.
Learners submit a single .html file with no external CSS.
"""

from bs4 import BeautifulSoup


# ── Helper ────────────────────────────────────────────────────────────────────

def _load(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return BeautifulSoup(f.read(), "html.parser")


def _normalize(value):
    if value is None:
        return ""
    return str(value).strip().upper()


# ── Tag existence checks ──────────────────────────────────────────────────────

def tag_exists(filepath, tag):
    """
    Check if a tag exists anywhere in the document.
    Example: tag_exists(fp, 'table')
    """
    soup = _load(filepath)
    return soup.find(tag) is not None


def tag_count(filepath, tag, expected_count):
    """Check if a specific tag appears an exact number of times."""
    soup = _load(filepath)
    return len(soup.find_all(tag)) == expected_count


def tag_count_at_least(filepath, tag, minimum):
    """Check if a tag appears at least a minimum number of times."""
    soup = _load(filepath)
    return len(soup.find_all(tag)) >= minimum


# ── Tag attribute checks ──────────────────────────────────────────────────────

def tag_has_attribute(filepath, tag, attribute, expected_value=None):
    """
    Check if a tag has a specific attribute, optionally with a specific value.
    Example: tag_has_attribute(fp, 'table', 'border', '1')
    """
    soup = _load(filepath)
    elements = soup.find_all(tag)
    for el in elements:
        if el.has_attr(attribute):
            if expected_value is None:
                return True
            if _normalize(el[attribute]) == _normalize(expected_value):
                return True
    return False


def tag_attribute_contains(filepath, tag, attribute, substring):
    """Check if any matching tag's attribute value contains a substring."""
    soup = _load(filepath)
    for el in soup.find_all(tag):
        if el.has_attr(attribute):
            if substring.upper() in str(el[attribute]).upper():
                return True
    return False


# ── Tag text / content checks ─────────────────────────────────────────────────

def tag_text(filepath, tag, expected, exact=False):
    """
    Check if any instance of a tag contains expected text.
    Set exact=True for exact match, otherwise substring match.
    """
    soup = _load(filepath)
    for el in soup.find_all(tag):
        text = el.get_text(strip=True)
        if exact:
            if text == expected:
                return True
        else:
            if expected.upper() in text.upper():
                return True
    return False


def title_text(filepath, expected):
    """Check if the <title> tag contains expected text."""
    soup = _load(filepath)
    title = soup.find("title")
    if not title:
        return False
    return expected.upper() in title.get_text().upper()


def body_contains_text(filepath, expected):
    """Check if the visible body text contains a string."""
    soup = _load(filepath)
    body = soup.find("body")
    if not body:
        return False
    return expected.upper() in body.get_text().upper()


# ── Inline style checks ───────────────────────────────────────────────────────

def tag_has_style(filepath, tag, css_property, expected_value=None):
    """
    Check if any instance of a tag has an inline style property.
    Optionally check the value.
    Example: tag_has_style(fp, 'p', 'color', 'red')
    """
    soup = _load(filepath)
    for el in soup.find_all(tag):
        style = el.get("style", "")
        if not style:
            continue
        # Parse inline style string into a dict
        styles = {}
        for declaration in style.split(";"):
            if ":" in declaration:
                prop, _, val = declaration.partition(":")
                styles[prop.strip().lower()] = val.strip().lower()

        if css_property.lower() in styles:
            if expected_value is None:
                return True
            if styles[css_property.lower()] == expected_value.lower():
                return True
    return False


# ── Structure checks ──────────────────────────────────────────────────────────

def has_doctype(filepath):
    """Check if the file starts with a DOCTYPE declaration."""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read(100).strip().upper()
    return content.startswith("<!DOCTYPE")


def tag_nested_in(filepath, child_tag, parent_tag):
    """
    Check if a child tag exists inside a parent tag.
    Example: tag_nested_in(fp, 'li', 'ul') — checks <li> is inside <ul>
    """
    soup = _load(filepath)
    parent = soup.find(parent_tag)
    if not parent:
        return False
    return parent.find(child_tag) is not None


def table_has_rows(filepath, expected_rows, table_index=0):
    """Check if a table has an expected number of <tr> rows."""
    soup = _load(filepath)
    tables = soup.find_all("table")
    if table_index >= len(tables):
        return False
    rows = tables[table_index].find_all("tr")
    return len(rows) == expected_rows


def table_has_headers(filepath, table_index=0):
    """Check if a table contains at least one <th> element."""
    soup = _load(filepath)
    tables = soup.find_all("table")
    if table_index >= len(tables):
        return False
    return len(tables[table_index].find_all("th")) > 0


def link_exists(filepath, href=None):
    """
    Check if an <a> tag exists. Optionally check the href value.
    Example: link_exists(fp, href='contact.html')
    """
    soup = _load(filepath)
    for a in soup.find_all("a"):
        if href is None:
            return True
        if _normalize(a.get("href", "")) == _normalize(href):
            return True
    return False


def image_exists(filepath, src=None):
    """
    Check if an <img> tag exists. Optionally check the src value.
    """
    soup = _load(filepath)
    for img in soup.find_all("img"):
        if src is None:
            return True
        if _normalize(img.get("src", "")) == _normalize(src):
            return True
    return False
