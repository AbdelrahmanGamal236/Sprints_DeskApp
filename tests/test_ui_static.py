"""Static UI rules from the spec."""
import re
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "app" / "ui"
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿←-⇿⬀-⯿]")
OFF_PALETTE = re.compile(r"#(3B82F6|1E3A8A|60A5FA|4F46E5|312E81|818CF8|E0E7FF|06B6D4|94A3B8|64748B|CBD5E1|1E293B|F8FAFC)", re.I)


class TestUiRules(unittest.TestCase):
    def _scan(self, pattern):
        hits = []
        for f in sorted(UI.glob("*.py")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{f.name}:{i}")
        return hits

    def test_no_emojis_or_arrow_glyphs(self):
        self.assertEqual(self._scan(EMOJI), [])

    def test_zinc_purple_palette_only(self):
        self.assertEqual(self._scan(OFF_PALETTE), [])


class TestNoUndefinedNames(unittest.TestCase):
    def test_no_undefined_names(self):
        """A missing import only fails when its button is clicked; catch it before release."""
        try:
            from pyflakes import api, messages, reporter
        except ImportError:
            self.skipTest("pyflakes not installed (pip install -r requirements-dev.txt)")
        root = UI.parent.parent
        found = []

        class Collect(reporter.Reporter):
            def __init__(self):
                pass

            def flake(self, msg):
                if isinstance(msg, (messages.UndefinedName, messages.UndefinedLocal)):
                    found.append(str(msg))

            def syntaxError(self, filename, msg, lineno, offset, text):
                found.append(f"{filename}:{lineno}: {msg}")

            def unexpectedError(self, filename, msg):
                found.append(f"{filename}: {msg}")

        paths = [str(f) for f in sorted((root / "app").rglob("*.py"))] + [str(root / "main.py"), str(root / "server_main.py")]
        api.checkRecursive(paths, Collect())
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
