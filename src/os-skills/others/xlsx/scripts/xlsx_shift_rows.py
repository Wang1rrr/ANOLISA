#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
xlsx_shift_rows.py — Shift all row references in an unpacked xlsx working directory
after inserting or deleting rows.

Usage:
    # Insert 2 rows at row 5 (rows 5+ shift down by 2)
    python3 xlsx_shift_rows.py <work_dir> insert 5 2

    # Delete 1 row at row 8 (rows 9+ shift up by 1)
    python3 xlsx_shift_rows.py <work_dir> delete 8 1

What it updates in every XML file under <work_dir>:
  - <row r="N"> attributes in worksheet sheetData
  - <c r="XN"> cell address attributes in worksheet sheetData
  - <f> formula text: absolute row references (e.g. B7, $B$7, $B7) in all sheets
  - <mergeCell ref="A5:C7"> ranges
  - <conditionalFormatting sqref="..."> ranges
  - <dataValidations sqref="..."> ranges
  - <dimension ref="A1:D20"> extent marker
  - Table <table ref="A1:D20"> in xl/tables/*.xml
  - Chart series <numRef><f> and <strRef><f> range references in xl/charts/*.xml
  - PivotCache source <worksheetSource ref="..."> in xl/pivotCaches/*.xml
  - Direct named ranges, print areas and print titles in xl/workbook.xml

IMPORTANT: Run this script on the UNPACKED directory before repacking.
After running, repack with xlsx_pack.py and re-validate with formula_check.py.

Limitations:
  - Direct defined-name cells/ranges, unions and print titles are updated.
    Complex expressions, external/3D references and out-of-grid names remain manual.
  - Structured table references (Table[@Column]) are NOT updated.
  - External workbook links in xl/externalLinks/ are NOT updated.
"""

import sys
import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import xml.dom.minidom


def col_letter(n: int) -> str:
    """Convert 1-based column number to Excel column letter(s)."""
    r = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        r = chr(65 + rem) + r
    return r


def col_number(s: str) -> int:
    """Convert Excel column letter(s) to 1-based column number."""
    n = 0
    for c in s.upper():
        n = n * 26 + (ord(c) - 64)
    return n


# ---------------------------------------------------------------------------
# Core shifting logic for formula strings
# ---------------------------------------------------------------------------

def _shift_refs(text: str, at: int, delta: int) -> str:
    """Shift cell references in a non-quoted formula fragment."""
    def replacer(m: re.Match) -> str:
        dollar_col = m.group(1)   # "$" or ""
        col_part = m.group(2)     # e.g. "B" or "AB"
        dollar_row = m.group(3)   # "$" or ""
        row_str = m.group(4)      # e.g. "7"
        row = int(row_str)
        if row >= at:
            row = max(1, row + delta)
        return f"{dollar_col}{col_part}{dollar_row}{row}"

    pattern = r'(\$?)([A-Z]+)(\$?)(\d+)'
    return re.sub(pattern, replacer, text)


def shift_formula(formula: str, at: int, delta: int) -> str:
    """
    Shift absolute and mixed row references >= `at` by `delta` in a formula string.

    Handles:
      B7       (relative col, absolute row — shifts if row >= at)
      $B$7     (absolute col, absolute row — shifts)
      $B7      (absolute col, relative row — shifts)
      B$7      (relative col, absolute — shifts)
      BUT NOT:  B:B  (whole-column reference — left as-is)

    Skips content inside single-quoted sheet name prefixes to avoid
    corrupting names like 'Budget FY2025' (where FY2025 is NOT a cell ref).

    Does NOT handle:
      - Named ranges
      - Structured references (Table[@Col])
      - R1C1 notation
    """
    # Split on quoted sheet names: 'Sheet Name' portions are odd-indexed
    segments = re.split(r"('[^']*(?:''[^']*)*')", formula)
    result = []
    for i, seg in enumerate(segments):
        if i % 2 == 1:
            result.append(seg)
        else:
            result.append(_shift_refs(seg, at, delta))
    return "".join(result)


def shift_sqref(sqref: str, at: int, delta: int) -> str:
    """
    Shift row references in a sqref string (space-separated cell/range addresses).
    E.g. "A5:D20 B30" → shift rows >= 5 by delta.
    """
    parts = sqref.split()
    result = []
    for part in parts:
        if ':' in part:
            left, right = part.split(':', 1)
            left = shift_formula(left, at, delta)
            right = shift_formula(right, at, delta)
            result.append(f"{left}:{right}")
        else:
            result.append(shift_formula(part, at, delta))
    return " ".join(result)


def shift_chart_range(text: str, at: int, delta: int) -> str:
    """
    Shift row references inside a chart range formula like:
      Sheet1!$B$5:$B$20
      'Q1 Data'!$A$3:$A$15
    """
    # Split on the "!" to preserve sheet name
    if '!' not in text:
        return text
    bang = text.index('!')
    sheet_part = text[:bang + 1]
    range_part = text[bang + 1:]
    return sheet_part + shift_formula(range_part, at, delta)


# ---------------------------------------------------------------------------
# XML file processors
# ---------------------------------------------------------------------------

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/chartDrawing"

# Namespace map used by ElementTree for tag lookup
NSMAP = {"ss": NS_MAIN}


def _tag(local: str) -> str:
    return f"{{{NS_MAIN}}}{local}"


def shift_defined_range(text: str, at: int, delta: int) -> str:
    """Shift only complete direct-reference unions; keep other definitions intact."""
    prefix = "=" if text.startswith("=") else ""
    expression = text[len(prefix) :]
    parts = []
    start = 0
    quoted = False
    i = 0
    while i < len(expression):
        character = expression[i]
        if character == "'":
            if quoted and i + 1 < len(expression) and expression[i + 1] == "'":
                i += 2
                continue
            quoted = not quoted
        elif character == "," and not quoted:
            parts.append(expression[start:i])
            start = i + 1
        i += 1
    if quoted:
        return text
    parts.append(expression[start:])

    cell = r"(\$?)([A-Za-z]{1,3})(\$?)([0-9]+)"
    row = r"(\$?)([0-9]+)"
    column = r"\$?([A-Za-z]{1,3})"
    qualifier = r"(?:(?:'(?:[^']|'')+'|[\w.]+)!)?"
    shifted = []
    for part in parts:
        match = re.fullmatch(r"(\s*)(" + qualifier + r")([^\s]+)(\s*)", part)
        if match is None:
            return text
        before, sheet, area, after = match.groups()
        if any(character in sheet for character in "[]:"):
            return text
        endpoints = area.split(":")
        if len(endpoints) > 2:
            return text
        cells = [re.fullmatch(cell, endpoint) for endpoint in endpoints]
        rows = [re.fullmatch(row, endpoint) for endpoint in endpoints]
        columns = [re.fullmatch(column, endpoint) for endpoint in endpoints]
        updated = []
        if all(cells):
            for address in cells:
                dollar_col, letters, dollar_row, number = address.groups()
                if not 1 <= col_number(letters) <= 16384:
                    return text
                old = int(number)
                new = max(1, old + delta) if old >= at else old
                if not 1 <= old <= 1048576 or not 1 <= new <= 1048576:
                    return text
                updated.append(f"{dollar_col}{letters}{dollar_row}{new}")
        elif len(endpoints) == 2 and all(rows):
            for address in rows:
                dollar, number = address.groups()
                old = int(number)
                new = max(1, old + delta) if old >= at else old
                if not 1 <= old <= 1048576 or not 1 <= new <= 1048576:
                    return text
                updated.append(f"{dollar}{new}")
        elif len(endpoints) == 2 and all(columns):
            if any(not 1 <= col_number(address.group(1)) <= 16384 for address in columns):
                return text
            updated = endpoints
        else:
            return text
        shifted.append(before + sheet + ":".join(updated) + after)
    return prefix + ",".join(shifted)


def process_defined_names(path: str, at: int, delta: int, dry_run: bool = False) -> int:
    """Update direct workbook ranges without losing compatibility declarations or text."""
    document = minidom.parse(path)
    changes = 0
    for name in document.getElementsByTagNameNS(NS_MAIN, "definedName"):
        if any(child.nodeType == child.ELEMENT_NODE for child in name.childNodes):
            continue
        old = "".join(
            child.data
            for child in name.childNodes
            if child.nodeType in (child.TEXT_NODE, child.CDATA_SECTION_NODE)
        )
        new = shift_defined_range(old, at, delta)
        if new != old:
            for child in list(name.childNodes):
                if child.nodeType in (child.TEXT_NODE, child.CDATA_SECTION_NODE):
                    name.removeChild(child)
            name.appendChild(document.createTextNode(new))
            changes += 1
    if changes and not dry_run:
        # DOM retains namespace aliases used by mc:Ignorable/QName values, comments,
        # and whitespace in other names. Pretty-print filtering would alter them.
        content = document.toxml(encoding="utf-8", standalone=document.standalone)
        with open(path, "wb") as stream:
            stream.write(content.replace(b"\r", b"&#13;"))
    return changes


def process_worksheet(path: str, at: int, delta: int) -> int:
    """Update row/cell references in a worksheet XML. Returns change count."""
    tree = ET.parse(path)
    root = tree.getroot()
    changes = 0

    # 1. <dimension ref="A1:D20">
    for dim in root.iter(_tag("dimension")):
        old = dim.get("ref", "")
        new = shift_sqref(old, at, delta)
        if new != old:
            dim.set("ref", new)
            changes += 1

    # 2. <row r="N"> and <c r="XN"> inside sheetData
    sheet_data = root.find(_tag("sheetData"))
    if sheet_data is not None:
        rows_to_reorder = []
        for row_el in list(sheet_data):
            r_str = row_el.get("r")
            if r_str is None:
                continue
            r = int(r_str)
            if r >= at:
                new_r = max(1, r + delta)
                row_el.set("r", str(new_r))
                changes += 1
                # Update each cell's r attribute
                for cell_el in row_el:
                    cell_ref = cell_el.get("r", "")
                    if cell_ref:
                        new_ref = shift_formula(cell_ref, at, delta)
                        if new_ref != cell_ref:
                            cell_el.set("r", new_ref)
                            changes += 1

            # Also update formulas in every row (formulas can reference any row)
            for cell_el in row_el:
                f_el = cell_el.find(_tag("f"))
                if f_el is not None and f_el.text:
                    new_f = shift_formula(f_el.text, at, delta)
                    if new_f != f_el.text:
                        f_el.text = new_f
                        changes += 1

    # 3. <mergeCell ref="A5:C7">
    for mc in root.iter(_tag("mergeCell")):
        old = mc.get("ref", "")
        new = shift_sqref(old, at, delta)
        if new != old:
            mc.set("ref", new)
            changes += 1

    # 4. <conditionalFormatting sqref="...">
    for cf in root.iter(_tag("conditionalFormatting")):
        old = cf.get("sqref", "")
        new = shift_sqref(old, at, delta)
        if new != old:
            cf.set("sqref", new)
            changes += 1

    # 5. <dataValidation sqref="...">
    for dv in root.iter(_tag("dataValidation")):
        old = dv.get("sqref", "")
        new = shift_sqref(old, at, delta)
        if new != old:
            dv.set("sqref", new)
            changes += 1

    if changes > 0:
        _write_tree(tree, path)
    return changes


def process_chart(path: str, at: int, delta: int) -> int:
    """Update data range references in a chart XML."""
    # Charts use DrawingML namespace; we look for <f> elements with range strings
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()

    # Pattern matches content of <f>Sheet1!$A$1:$A$10</f> style elements
    def replace_f(m: re.Match) -> str:
        tag_open = m.group(1)
        inner = m.group(2)
        tag_close = m.group(3)
        new_inner = shift_chart_range(inner, at, delta)
        return f"{tag_open}{new_inner}{tag_close}"

    new_content = re.sub(r'(<(?:[^:>]+:)?f>)([^<]+)(</(?:[^:>]+:)?f>)',
                          replace_f, content)
    changes = content != new_content
    if changes:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new_content)
    return 1 if changes else 0


def process_table(path: str, at: int, delta: int) -> int:
    """Update the ref attribute on the <table> root element."""
    tree = ET.parse(path)
    root = tree.getroot()
    # The root element IS the table
    old = root.get("ref", "")
    if not old:
        return 0
    new = shift_sqref(old, at, delta)
    if new == old:
        return 0
    root.set("ref", new)
    _write_tree(tree, path)
    return 1


def process_pivot_cache(path: str, at: int, delta: int) -> int:
    """Update worksheetSource ref in a pivot cache definition."""
    tree = ET.parse(path)
    root = tree.getroot()
    changes = 0
    # Look for <worksheetSource ref="A1:D100" ...>
    for ws in root.iter():
        if ws.tag.endswith("}worksheetSource") or ws.tag == "worksheetSource":
            old = ws.get("ref", "")
            if old:
                new = shift_sqref(old, at, delta)
                if new != old:
                    ws.set("ref", new)
                    changes += 1
    if changes:
        _write_tree(tree, path)
    return changes


def _write_tree(tree: ET.ElementTree, path: str) -> None:
    """Write ElementTree back to file with pretty-printing."""
    tree.write(path, encoding="unicode", xml_declaration=False)
    # Re-pretty-print for readability
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        dom = xml.dom.minidom.parseString(raw.encode("utf-8"))
        pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        lines = [line for line in pretty.splitlines() if line.strip()]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass  # If pretty-print fails, leave the file as-is


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    work_dir = sys.argv[1]
    operation = sys.argv[2].lower()
    at = int(sys.argv[3])
    count = int(sys.argv[4])

    if operation not in ("insert", "delete"):
        print(f"ERROR: operation must be 'insert' or 'delete', got '{operation}'")
        sys.exit(1)

    if operation == "insert":
        delta = count
    else:
        delta = -count

    if not os.path.isdir(work_dir):
        print(f"ERROR: Directory not found: {work_dir}")
        sys.exit(1)

    print(f"Operation : {operation} {count} row(s) at row {at} (delta={delta:+d})")
    print(f"Work dir  : {work_dir}")
    print()

    total_changes = 0

    # Defined names follow the same global shift as all worksheets.
    workbook_path = os.path.join(work_dir, "xl", "workbook.xml")
    if os.path.isfile(workbook_path):
        n = process_defined_names(workbook_path, at, delta)
        if n:
            print(f"  Updated {n:3d} defined names in xl/workbook.xml")
            total_changes += n

    # Process all worksheets
    ws_dir = os.path.join(work_dir, "xl", "worksheets")
    if os.path.isdir(ws_dir):
        for fname in sorted(os.listdir(ws_dir)):
            if fname.endswith(".xml"):
                fpath = os.path.join(ws_dir, fname)
                n = process_worksheet(fpath, at, delta)
                if n:
                    print(f"  Updated {n:3d} references in xl/worksheets/{fname}")
                    total_changes += n

    # Process all charts
    charts_dir = os.path.join(work_dir, "xl", "charts")
    if os.path.isdir(charts_dir):
        for fname in sorted(os.listdir(charts_dir)):
            if fname.endswith(".xml"):
                fpath = os.path.join(charts_dir, fname)
                n = process_chart(fpath, at, delta)
                if n:
                    print(f"  Updated chart ranges in xl/charts/{fname}")
                    total_changes += n

    # Process all tables
    tables_dir = os.path.join(work_dir, "xl", "tables")
    if os.path.isdir(tables_dir):
        for fname in sorted(os.listdir(tables_dir)):
            if fname.endswith(".xml"):
                fpath = os.path.join(tables_dir, fname)
                n = process_table(fpath, at, delta)
                if n:
                    print(f"  Updated table ref in xl/tables/{fname}")
                    total_changes += n

    # Process pivot cache definitions
    cache_dir = os.path.join(work_dir, "xl", "pivotCaches")
    if os.path.isdir(cache_dir):
        for fname in sorted(os.listdir(cache_dir)):
            if "Definition" in fname and fname.endswith(".xml"):
                fpath = os.path.join(cache_dir, fname)
                n = process_pivot_cache(fpath, at, delta)
                if n:
                    print(f"  Updated pivot source range in xl/pivotCaches/{fname}")
                    total_changes += n

    print()
    print(f"Total changes: {total_changes}")
    print()
    print("IMPORTANT: Review complex, external/3D and out-of-grid defined names manually.")
    print("           Structured table references (Table[@Col]) are NOT updated.")
    print()
    print("Next steps:")
    print("  1. Review the changes above")
    print(f"  2. python3 xlsx_pack.py {work_dir} output.xlsx")
    print("  3. python3 formula_check.py output.xlsx")


if __name__ == "__main__":
    main()
