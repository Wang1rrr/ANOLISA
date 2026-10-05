"""Check completed workbook publication and preservation across I/O failures."""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "src/os-skills/others/xlsx/scripts/xlsx_pack.py"
SPEC = importlib.util.spec_from_file_location("xlsx_pack_publication", SCRIPT)
PACKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKER)


class WorkbookPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="xlsx-publication-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "[Content_Types].xml").write_bytes(b"<Types/>\n")
        (self.source / "xl").mkdir()
        (self.source / "xl/workbook.xml").write_bytes(b"<workbook/>\n")
        self.output = self.base / "previous workbook.xlsx"

    def previous_archive(self) -> bytes:
        with zipfile.ZipFile(self.output, "w") as archive:
            archive.writestr("previous.xml", "<previous/>\n")
        return self.output.read_bytes()

    def pack(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            PACKER.pack(str(self.source), str(self.output))

    def fail_after_first_member(self) -> None:
        original = zipfile.ZipFile.write
        writes = 0

        def write(archive: zipfile.ZipFile, *arguments: object, **kwargs: object) -> None:
            nonlocal writes
            if writes:
                raise OSError("member read failed")
            writes += 1
            original(archive, *arguments, **kwargs)

        with patch.object(zipfile.ZipFile, "write", write):
            with self.assertRaisesRegex(OSError, "member read failed"):
                self.pack()

    def test_member_failure_preserves_previous_complete_archive(self) -> None:
        previous = self.previous_archive()
        names = set(self.base.iterdir())
        self.fail_after_first_member()
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(set(self.base.iterdir()), names)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.testzip(), None)
            self.assertEqual(archive.read("previous.xml"), b"<previous/>\n")

    def test_member_failure_does_not_publish_new_partial_archive(self) -> None:
        names = set(self.base.iterdir())
        self.fail_after_first_member()
        self.assertFalse(self.output.exists())
        self.assertEqual(set(self.base.iterdir()), names)

    def test_success_replaces_previous_archive_with_exact_members(self) -> None:
        self.previous_archive()
        self.pack()
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), {"[Content_Types].xml", "xl/workbook.xml"})
            self.assertEqual(archive.read("xl/workbook.xml"), b"<workbook/>\n")
        self.assertEqual(set(self.base.iterdir()), {self.source, self.output})

    def test_publication_failure_preserves_previous_archive_and_cleans_staging(self) -> None:
        previous = self.previous_archive()
        names = set(self.base.iterdir())
        with patch.object(PACKER.os, "replace", side_effect=OSError("publication failed")):
            with self.assertRaisesRegex(OSError, "publication failed"):
                self.pack()
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(set(self.base.iterdir()), names)

    def test_xml_validation_failure_preserves_existing_archive(self) -> None:
        previous = self.previous_archive()
        (self.source / "xl/workbook.xml").write_text("<invalid", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.pack()
        self.assertEqual(self.output.read_bytes(), previous)

    @unittest.skipUnless(os.name == "posix", "POSIX modes")
    def test_existing_archive_permissions_are_preserved(self) -> None:
        self.previous_archive()
        self.output.chmod(0o640)
        self.pack()
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o640)

    @unittest.skipUnless(os.name == "posix", "POSIX modes")
    def test_new_archive_uses_the_normal_creation_mode(self) -> None:
        control = self.base / "ordinary.zip"
        with zipfile.ZipFile(control, "w") as archive:
            archive.writestr("control", "sample")
        self.pack()
        self.assertEqual(self.output.stat().st_mode & 0o777, control.stat().st_mode & 0o777)

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks")
    def test_existing_output_symlink_remains_a_link_to_updated_archive(self) -> None:
        self.previous_archive()
        actual = self.base / "actual.xlsx"
        self.output.rename(actual)
        self.output.symlink_to(actual)
        self.pack()
        self.assertTrue(self.output.is_symlink())
        with zipfile.ZipFile(actual) as archive:
            self.assertEqual(set(archive.namelist()), {"[Content_Types].xml", "xl/workbook.xml"})


if __name__ == "__main__":
    unittest.main()
