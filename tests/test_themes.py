"""Tests for the YAML theme files under ``gitnc/themes/``."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from typing import Any


def _install_textual_stubs() -> None:
    """Provide stub ``textual.theme`` so ``UITheme`` is importable headlessly."""
    textual: Any = types.ModuleType("textual")
    textual_theme: Any = types.ModuleType("textual.theme")

    class Theme:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.name = kwargs.get("name", args[0] if args else "")

    textual_theme.Theme = Theme
    sys.modules.setdefault("textual", textual)
    sys.modules.setdefault("textual.theme", textual_theme)


try:
    from gitnc.themes import THEMES_DIR, load_all, theme_files
    from gitnc.ui_theme import UITheme
except ModuleNotFoundError as exc:
    if exc.name not in {"textual", "textual.theme"}:
        raise
    _install_textual_stubs()
    from gitnc.themes import THEMES_DIR, load_all, theme_files
    from gitnc.ui_theme import UITheme


class TestThemeYamlFiles(unittest.TestCase):
    def test_at_least_one_theme_yaml_file_exists(self):
        self.assertTrue(theme_files(), "no *.yaml files found under gitnc/themes/")

    def test_every_theme_yaml_loads_as_uitheme(self):
        for path in theme_files():
            with self.subTest(path=path.name):
                theme = UITheme.load(path)
                self.assertIsInstance(theme, UITheme)

    def test_load_all_returns_uitheme_instances(self):
        themes = load_all()
        self.assertEqual(len(themes), len(theme_files()))
        for theme in themes:
            self.assertIsInstance(theme, UITheme)

    def test_yaml_file_name_matches_theme_name(self):
        for path in theme_files():
            with self.subTest(path=path.name):
                theme = UITheme.load(path)
                self.assertEqual(theme.name, path.stem)

    def test_load_rejects_yaml_missing_required_fields(self):
        # Drop one required field and assert load() fails with a clear error.
        sample = THEMES_DIR / "midnight-commander.yaml"
        text = sample.read_text(encoding="utf-8")
        broken_path = Path(self._tempdir()) / "broken.yaml"
        broken_path.write_text(
            "\n".join(line for line in text.splitlines() if not line.startswith("primary:")) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError) as ctx:
            UITheme.load(broken_path)
        self.assertIn("missing required field", str(ctx.exception))

    def _tempdir(self) -> str:
        import tempfile

        dirpath = tempfile.mkdtemp(prefix="gitnc-themes-test-")
        self.addCleanup(__import__("shutil").rmtree, dirpath, True)
        return dirpath


if __name__ == "__main__":
    unittest.main()
