"""Theme definitions, one YAML file per theme.

Each ``*.yaml`` file in this package describes a single UITheme. The file
name (without extension) matches the theme's ``name`` field. ``load_all``
discovers every YAML file in the package directory and returns the
resulting ``UITheme`` instances.
"""

from __future__ import annotations

from pathlib import Path

from ..ui_theme import UITheme

THEMES_DIR = Path(__file__).resolve().parent


def theme_files() -> list[Path]:
    """Return every theme YAML file in declaration-stable order."""
    return sorted(THEMES_DIR.glob("*.yaml"))


def load_all() -> list[UITheme]:
    """Load every theme YAML file as a UITheme instance."""
    return [UITheme.load(path) for path in theme_files()]
