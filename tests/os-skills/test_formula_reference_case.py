"""Validate reference lookup identity while retaining original report spelling."""

import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "src/os-skills/others/xlsx/scripts/formula_check.py"
SPEC = importlib.util.spec_from_file_location("formula_reference_case", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class FormulaReferenceCaseTests(unittest.TestCase):
    def check(self, formula: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="formula-case-") as temporary:
            output = Path(temporary) / "input.xlsx"
            workbook = ET.Element(f"{{{NS}}}workbook")
            sheets = ET.SubElement(workbook, f"{{{NS}}}sheets")
            for index, name in enumerate(("Summary", "Sales", "Data Tab", "Överview"), 1):
                ET.SubElement(
                    sheets,
                    f"{{{NS}}}sheet",
                    {"name": name, "sheetId": str(index), f"{{{REL}}}id": f"rId{index}"},
                )
            names = ET.SubElement(workbook, f"{{{NS}}}definedNames")
            ET.SubElement(names, f"{{{NS}}}definedName", {"name": "Interest_Rate"}).text = (
                "Sales!$A$1"
            )
            relationships = ET.Element("Relationships")
            for index in range(1, 5):
                ET.SubElement(
                    relationships,
                    "Relationship",
                    {"Id": f"rId{index}", "Target": f"worksheets/sheet{index}.xml"},
                )
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("xl/workbook.xml", ET.tostring(workbook))
                archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(relationships))
                for index in range(1, 5):
                    worksheet = ET.Element(f"{{{NS}}}worksheet")
                    data = ET.SubElement(worksheet, f"{{{NS}}}sheetData")
                    row = ET.SubElement(data, f"{{{NS}}}row", {"r": "1"})
                    cell = ET.SubElement(row, f"{{{NS}}}c", {"r": "A1"})
                    if index == 1:
                        ET.SubElement(cell, f"{{{NS}}}f").text = formula
                    else:
                        ET.SubElement(cell, f"{{{NS}}}v").text = "2"
                    archive.writestr(f"xl/worksheets/sheet{index}.xml", ET.tostring(worksheet))
            return CHECKER.check(str(output))

    def assert_valid(self, formula: str) -> None:
        result = self.check(formula)
        self.assertEqual(result["error_count"], 0, result["errors"])
        self.assertEqual(result["formula_count"], 1)
        self.assertEqual(result["sheets_checked"], ["Summary", "Sales", "Data Tab", "Överview"])

    def test_unquoted_sheet_lookup_ignores_case(self) -> None:
        for name in ("sales", "SALES", "sAlEs"):
            with self.subTest(name=name):
                self.assert_valid(f"{name}!A1*2")

    def test_quoted_sheet_lookup_ignores_case(self) -> None:
        self.assert_valid("'dAtA tAb'!A1*2")

    def test_quoted_non_ascii_sheet_case_is_supported(self) -> None:
        self.assert_valid("'överVIEW'!A1*2")

    def test_defined_name_lookup_ignores_case(self) -> None:
        for name in ("interest_rate", "INTEREST_RATE", "InTeReSt_RaTe"):
            with self.subTest(name=name):
                self.assert_valid(name + "*2")

    def test_exact_case_references_remain_valid(self) -> None:
        self.assert_valid("Sales!A1*Interest_Rate")

    def test_missing_sheet_report_keeps_original_names(self) -> None:
        result = self.check("MiSsInG!A1")
        error = next(error for error in result["errors"] if error["type"] == "broken_sheet_ref")
        self.assertEqual(error["missing_sheet"], "MiSsInG")
        self.assertEqual(
            error["valid_sheets"], sorted(["Summary", "Sales", "Data Tab", "Överview"])
        )

    def test_missing_name_report_keeps_original_names(self) -> None:
        result = self.check("MiSsInG_Rate*2")
        error = next(error for error in result["errors"] if error["type"] == "unknown_name_ref")
        self.assertEqual(error["unknown_name"], "MiSsInG_Rate")
        self.assertEqual(error["defined_names"], ["Interest_Rate"])


if __name__ == "__main__":
    unittest.main()
