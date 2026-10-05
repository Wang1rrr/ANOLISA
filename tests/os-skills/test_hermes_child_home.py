"""Run Hermes option parsing and observe the data home in a real child process."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "src/os-skills/ai/install-hermes/scripts/install.sh"


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "POSIX tools")
class HermesChildHomeTests(unittest.TestCase):
    def child_home(self, arguments: list[str], inherited: str | None = None) -> dict:
        with tempfile.TemporaryDirectory(prefix="hermes-home-") as temporary:
            directory = Path(temporary)
            script = directory / "installer.sh"
            source = SCRIPT.read_text(encoding="utf-8")
            self.assertRegex(source, r"\nmain\s*$")
            source = re.sub(r"\nmain\s*$", "\n", source)
            source += '"$TEST_PYTHON" "$TEST_CHILD"\n'
            script.write_text(source, encoding="utf-8")
            child = directory / "child.py"
            child.write_text(
                "import json, os\nfrom pathlib import Path\n"
                "home = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')\n"
                "print(json.dumps({'home': str(home), "
                "'parent_home': os.environ.get('HOME')}))\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.pop("HERMES_HOME", None)
            environment["TEST_PYTHON"] = sys.executable
            environment["TEST_CHILD"] = str(child)
            if inherited is not None:
                environment["HERMES_HOME"] = inherited
            result = subprocess.run(
                ["bash", str(script), *arguments],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return json.loads(result.stdout)

    def test_option_home_reaches_child_without_an_inherited_variable(self) -> None:
        result = self.child_home(["--hermes-home", "/tmp/custom-hermes"])
        self.assertEqual(result["home"], "/tmp/custom-hermes")

    def test_option_home_with_spaces_and_explicit_checkout_reaches_child(self) -> None:
        result = self.child_home(
            [
                "--dir",
                "/tmp/explicit checkout",
                "--hermes-home",
                "/tmp/custom Hermes data",
            ]
        )
        self.assertEqual(result["home"], "/tmp/custom Hermes data")

    def test_default_home_reaches_child(self) -> None:
        result = self.child_home([])
        self.assertEqual(result["home"], str(Path(result["parent_home"]) / ".hermes"))

    def test_inherited_home_remains_compatible(self) -> None:
        self.assertEqual(self.child_home([], "/tmp/inherited-home")["home"], "/tmp/inherited-home")

    def test_option_overrides_inherited_home(self) -> None:
        result = self.child_home(["--hermes-home", "/tmp/selected-home"], "/tmp/inherited-home")
        self.assertEqual(result["home"], "/tmp/selected-home")


if __name__ == "__main__":
    unittest.main()
