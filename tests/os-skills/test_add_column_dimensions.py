"""Exercise worksheet extents through the real add-column CLI and XLSX readers."""

import io
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "src/os-skills/others/xlsx"
SCRIPT = SKILL / "scripts/xlsx_add_column.py"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

try:
    import openpyxl
except ImportError:
    openpyxl = None


class AddColumnDimensionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name) / "unpacked"
        shutil.copytree(SKILL / "templates/minimal_xlsx", self.work)
        # Materialize the template as ordinary XML, without instructional comments.
        for part in self.work.rglob("*.xml"):
            ET.parse(part).write(part, encoding="utf-8", xml_declaration=True)
        relationships = self.work / "xl/_rels/workbook.xml.rels"
        relationships.write_text(
            relationships.read_text(encoding="utf-8").replace(
                'Target="worksheets/sheet1.xml"', 'Target="/xl/worksheets/sheet1.xml"'
            ),
            encoding="utf-8",
        )
        self.sheet = self.work / "xl/worksheets/sheet1.xml"

    def fixture(self, dimension: str | None, refs: tuple[str, ...]) -> None:
        root = ET.Element(f"{{{NS}}}worksheet")
        if dimension is not None:
            ET.SubElement(root, f"{{{NS}}}dimension", ref=dimension)
        ET.SubElement(root, f"{{{NS}}}sheetViews")
        data = ET.SubElement(root, f"{{{NS}}}sheetData")
        rows = {}
        for reference in refs:
            number = "".join(character for character in reference if character.isdigit())
            if number not in rows:
                rows[number] = ET.SubElement(data, f"{{{NS}}}row", r=number)
            cell = ET.SubElement(rows[number], f"{{{NS}}}c", r=reference)
            ET.SubElement(cell, f"{{{NS}}}v").text = "1"
        ET.ElementTree(root).write(self.sheet, encoding="utf-8", xml_declaration=True)

    def add(self, *arguments: str) -> ET.Element:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.work), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return ET.parse(self.sheet).getroot()

    def extent(self, root: ET.Element) -> str | None:
        dimension = root.find(f"{{{NS}}}dimension")
        return dimension.get("ref") if dimension is not None else None

    def test_formulas_extend_row_and_column_bounds(self) -> None:
        self.fixture("A1:F2", ("A1", "F2"))
        root = self.add("--col", "G", "--formula", "=1", "--formula-rows", "3:5")
        self.assertEqual(self.extent(root), "A1:G5")

    def test_total_formula_extends_the_row_bound(self) -> None:
        self.fixture("A1:F2", ("A1", "F2"))
        root = self.add("--col", "G", "--total-row", "10", "--total-formula", "=SUM(G2:G9)")
        self.assertEqual(self.extent(root), "A1:G10")

    def test_single_cell_dimension_becomes_a_rectangle(self) -> None:
        self.fixture("A1", ("A1",))
        root = self.add("--col", "G", "--formula", "=1", "--formula-rows", "2:3")
        self.assertEqual(self.extent(root), "A1:G3")

    def test_missing_dimension_includes_existing_sparse_cells(self) -> None:
        self.fixture(None, ("C3", "D5"))
        root = self.add("--col", "G", "--formula", "=1", "--formula-rows", "6:6")
        self.assertEqual(self.extent(root), "C3:G6")
        children = [child.tag.rsplit("}", 1)[-1] for child in root]
        self.assertLess(children.index("dimension"), children.index("sheetViews"))

    def test_created_dimension_follows_sheet_properties(self) -> None:
        self.fixture(None, ("A1",))
        root = ET.parse(self.sheet).getroot()
        root.insert(0, ET.Element(f"{{{NS}}}sheetPr"))
        ET.ElementTree(root).write(self.sheet, encoding="utf-8", xml_declaration=True)
        root = self.add("--col", "G", "--formula", "=1", "--formula-rows", "2:3")
        children = [child.tag.rsplit("}", 1)[-1] for child in root]
        self.assertEqual(children[:3], ["sheetPr", "dimension", "sheetViews"])
        self.assertEqual(self.extent(root), "A1:G3")

    def test_added_cells_can_expand_the_top_left_corner(self) -> None:
        self.fixture("C3:D5", ("C3", "D5"))
        root = self.add("--col", "B", "--formula", "=1", "--formula-rows", "2:7")
        self.assertEqual(self.extent(root), "B2:D7")

    def test_larger_existing_extent_is_preserved(self) -> None:
        self.fixture("A1:K20", ("A1", "F2"))
        root = self.add("--col", "G", "--formula", "=1", "--formula-rows", "3:5")
        self.assertEqual(self.extent(root), "A1:K20")

    def test_no_cell_addition_does_not_expand_the_extent(self) -> None:
        self.fixture("A1:F2", ("A1", "F2"))
        root = self.add("--col", "G")
        self.assertEqual(self.extent(root), "A1:F2")

    @unittest.skipIf(openpyxl is None, "OpenPyXL is optional for the reader round trip")
    def test_read_only_reader_sees_all_added_formulas(self) -> None:
        self.fixture("A1:F2", ("A1", "F2"))
        self.add("--col", "G", "--formula", "=1", "--formula-rows", "3:5")
        output = Path(self.temporary.name) / "result.xlsx"
        with zipfile.ZipFile(output, "w") as archive:
            for member in self.work.rglob("*"):
                if member.is_file():
                    archive.write(member, member.relative_to(self.work).as_posix())
        stream = io.BytesIO(output.read_bytes())
        self.addCleanup(stream.close)
        workbook = openpyxl.load_workbook(stream, read_only=True, data_only=False)
        self.addCleanup(workbook.close)
        sheet = workbook.worksheets[0]
        formulas = [row[6] for row in sheet.iter_rows(values_only=True) if len(row) > 6]
        self.assertEqual(formulas[2:], ["=1", "=1", "=1"])


if __name__ == "__main__":
    unittest.main()
