"""Validate recovery of malformed OpenClaw device cache roots."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "src/os-skills/ai/install-openclaw/scripts/install_openclaw.py"
)
SPEC = importlib.util.spec_from_file_location("openclaw_device_auth_installer", SCRIPT)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class OpenClawDeviceAuthShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="openclaw-device-auth-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.path = self.base / "identity/device-auth.json"
        self.path.parent.mkdir()
        self.args = SimpleNamespace(config=str(self.base / "openclaw.json"))

    def write(self, value: object) -> bytes:
        payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.path.write_bytes(payload)
        return payload

    def test_non_object_roots_are_not_treated_as_authorized(self) -> None:
        for value in (None, [], ["operator.write"], "operator.write", True, 17):
            with self.subTest(value=value):
                payload = self.write(value)
                self.assertFalse(INSTALLER.cached_operator_has_write_scope(self.args))
                self.assertEqual(self.path.read_bytes(), payload)

    def test_non_object_roots_are_backed_up_before_reset(self) -> None:
        for value in (None, [], ["operator.write"], "operator.write", True, 17):
            with self.subTest(value=value):
                payload = self.write(value)
                INSTALLER.clear_cached_operator_device_auth(self.args)
                self.assertFalse(self.path.exists())
                self.assertEqual(self.path.with_suffix(".json.bak").read_bytes(), payload)

    def test_malformed_json_uses_existing_backup_recovery(self) -> None:
        payload = b'{"tokens":\n'
        self.path.write_bytes(payload)
        self.assertFalse(INSTALLER.cached_operator_has_write_scope(self.args))
        INSTALLER.clear_cached_operator_device_auth(self.args)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.path.with_suffix(".json.bak").read_bytes(), payload)

    def test_valid_write_scope_remains_authorized(self) -> None:
        for scope in ("operator.write", "operator.admin"):
            for value in (
                {"tokens": {"operator": {"scopes": [scope]}}},
                {"role": "operator", "scopes": [scope]},
            ):
                with self.subTest(value=value):
                    payload = self.write(value)
                    self.assertTrue(INSTALLER.cached_operator_has_write_scope(self.args))
                    self.assertEqual(self.path.read_bytes(), payload)

    def test_reset_removes_only_operator_token(self) -> None:
        value = {
            "tokens": {"operator": {"scopes": ["operator.read"]}, "node": {"token": "node-value"}},
            "custom": "keep",
        }
        self.write(value)
        INSTALLER.clear_cached_operator_device_auth(self.args)
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {"tokens": {"node": {"token": "node-value"}}, "custom": "keep"},
        )
        self.assertFalse(self.path.with_suffix(".json.bak").exists())

    def test_unknown_object_is_preserved(self) -> None:
        payload = self.write({"node": "keep"})
        self.assertFalse(INSTALLER.cached_operator_has_write_scope(self.args))
        INSTALLER.clear_cached_operator_device_auth(self.args)
        self.assertEqual(self.path.read_bytes(), payload)

    def test_backup_failure_retains_original_cache(self) -> None:
        payload = self.write(None)
        with patch.object(Path, "write_bytes", side_effect=OSError("backup unavailable")):
            with self.assertRaises(OSError):
                INSTALLER.clear_cached_operator_device_auth(self.args)
        self.assertEqual(self.path.read_bytes(), payload)

    def test_missing_cache_is_a_noop(self) -> None:
        self.assertFalse(INSTALLER.cached_operator_has_write_scope(self.args))
        INSTALLER.clear_cached_operator_device_auth(self.args)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
