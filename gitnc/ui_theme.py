"""Application-level theme definition."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml
from textual.theme import Theme

from .git import GitStatus

_THEME_REF_PATTERN = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_-]*)")


@dataclass
class UITheme:
    """Application-level theme definition.

    Mirrors the fields of textual.theme.Theme so the application can read
    colors directly (e.g. theme.background). Use get_theme() in the places
    where Textual itself requires a textual.theme.Theme instance.

    Beyond the textual.theme.Theme fields, this class adds semantically
    named color and style fields for everything the app renders itself
    (status codes, diff lines, dialog hints, the file cursor) so themes
    can customize each usage independently.
    """

    name: str
    primary: str
    secondary: str | None = None
    warning: str | None = None
    error: str | None = None
    success: str | None = None
    accent: str | None = None
    foreground: str | None = None
    background: str | None = None
    surface: str | None = None
    panel: str | None = None
    boost: str | None = None
    dark: bool = True
    luminosity_spread: float = 0.15
    text_alpha: float = 0.95
    variables: dict[str, str] = field(default_factory=dict)
    ansi: bool = False

    # Status-code colors used in the Status column of the file list.
    status_modified: str = "bold yellow"
    status_type_changed: str = "bold #ff8800"
    status_added: str = "bold green"
    status_deleted: str = "bold red"
    status_renamed: str = "bold cyan"
    status_copied: str = "bold blue"
    status_unmerged: str = "bold #ff5555"
    status_untracked: str = "bold white"
    status_ignored: str = "#888888"
    status_submodule: str = "bold magenta"

    # Diff line rendering (FileDiff).
    diff_added_line: str = "green"
    diff_added_line_number: str = "green dim"
    diff_removed_line: str = "red"
    diff_removed_line_number: str = "red dim"
    diff_context_line_number: str = "dim"

    # Commit detail rendering (CommitDetail): the `commit`/`Author:`/`Date:`
    # header block and the `@@ ... @@` hunk markers. The +/- lines and the
    # diffstat graph reuse the diff colors above so both diff views match.
    commit_header_line: str = "bold"
    diff_hunk_header: str = "cyan"

    # Confirm dialog Y/N hint.
    confirm_yes_key: str = "b green"
    confirm_no_key: str = "b red"

    # Warning text shown above the file list (e.g. submodule branch mismatches).
    warning_text: str = "bold red"

    # Faint hint text shown at the bottom of dialogs.
    dialog_hint: str = "dim"

    # The accelerator letter highlighted in a menu bar entry ("File") and in
    # every dropdown entry. Must stay readable on both the menu bar
    # ($menu-bar-background) and the dropdown ($panel) background, which is
    # why the default carries no color of its own.
    menu_mnemonic: str = "bold underline"

    # Settings dialog checkbox mark.
    checkbox_mark: str = "green"

    # The text caret in the settings dialog's editable rows. It is drawn on
    # the cell it sits on rather than after the text, so it has to swap that
    # cell's colors: a color of its own would hide the character under it.
    text_caret: str = "reverse"

    # CSS-side palette for the menu bar and the footer. The defaults are
    # Textual's own Header/Footer palette, so a theme that says nothing about
    # the chrome gets the bars every other Textual app has. A theme after a
    # Turbo Vision look overrides them (midnight-commander paints both bars in
    # $warning); tying them to a palette role here instead would repaint the
    # bars in whatever that role happens to mean in the next theme.
    menu_bar_background: str = "$panel"
    menu_bar_foreground: str = "$foreground"
    footer_background: str = "$panel"
    footer_foreground: str = "$foreground"

    # CSS-side palette for the file list cursor + multi-selection.
    cursor_row_background: str = "$primary"
    cursor_row_foreground: str = "$foreground"
    selected_file_background: str = "$warning 30%"
    selected_file_foreground: str = "$success"
    selected_cursor_row_background: str = "$primary"
    selected_cursor_row_foreground: str = "$success"

    def status_color_for(self, status: GitStatus) -> str:
        return _STATUS_FIELD_BY_STATUS[status](self)

    def status_color_map(self) -> dict[GitStatus, str]:
        return {status: getter(self) for status, getter in _STATUS_FIELD_BY_STATUS.items()}

    def _resolve_refs(self, value: str) -> str:
        """Replace ``$primary``, ``$warning``, … with this theme's own values.

        Why: Textual's CSS parser does a single-pass substitution. Storing a
        chained reference like ``cursor_row_background = "$primary"`` in the
        theme's ``variables`` dict produces a CSS error at app start because
        Textual only substitutes the outer ``$cursor-row-background`` and
        then treats the resulting ``"$primary"`` as a literal color value.
        Resolving the inner ref here keeps the CSS-side fields semantic
        while emitting concrete colors to Textual.
        How to apply: called from ``css_variables`` for every CSS-side
        field. Themes that don't set ``foreground`` / ``background`` /
        ``surface`` / ``panel`` (Textual derives those at runtime) fall
        back to a sensible black-or-white based on ``dark``, so the
        emitted CSS never contains an unresolved ``$ref``.
        """
        dark = self.dark
        light_text = "#f0f0f0"
        dark_text = "#111111"
        refs: dict[str, str] = {
            "primary": self.primary,
            "secondary": self.secondary or self.primary,
            "warning": self.warning or "#ffa62b",
            "error": self.error or "#ba3c5b",
            "success": self.success or "#4EBF71",
            "accent": self.accent or self.primary,
            "foreground": self.foreground or (light_text if dark else dark_text),
            "background": self.background or (dark_text if dark else light_text),
            "surface": self.surface or self.background or (dark_text if dark else light_text),
            "panel": self.panel or self.surface or self.background or self.primary,
            "boost": self.boost or self.primary,
        }

        def replace(match: re.Match[str]) -> str:
            return refs.get(match.group(1), match.group(0))

        return _THEME_REF_PATTERN.sub(replace, value)

    def css_variables(self) -> dict[str, str]:
        """CSS variables this theme contributes, with refs resolved."""
        return {
            "menu-bar-background": self._resolve_refs(self.menu_bar_background),
            "menu-bar-foreground": self._resolve_refs(self.menu_bar_foreground),
            "footer-background": self._resolve_refs(self.footer_background),
            "footer-foreground": self._resolve_refs(self.footer_foreground),
            "cursor-row-background": self._resolve_refs(self.cursor_row_background),
            "cursor-row-foreground": self._resolve_refs(self.cursor_row_foreground),
            "selected-file-background": self._resolve_refs(self.selected_file_background),
            "selected-file-foreground": self._resolve_refs(self.selected_file_foreground),
            "selected-cursor-row-background": self._resolve_refs(
                self.selected_cursor_row_background
            ),
            "selected-cursor-row-foreground": self._resolve_refs(
                self.selected_cursor_row_foreground
            ),
        }

    def get_theme(self) -> Theme:
        css_vars = dict(self.variables)
        for name, value in self.css_variables().items():
            css_vars.setdefault(name, value)
        return Theme(
            name=self.name,
            primary=self.primary,
            secondary=self.secondary,
            warning=self.warning,
            error=self.error,
            success=self.success,
            accent=self.accent,
            foreground=self.foreground,
            background=self.background,
            surface=self.surface,
            panel=self.panel,
            boost=self.boost,
            dark=self.dark,
            luminosity_spread=self.luminosity_spread,
            text_alpha=self.text_alpha,
            variables=css_vars,
            ansi=self.ansi,
        )

    @classmethod
    def load(cls, path: str | Path) -> UITheme:
        """Load a UITheme from a YAML file.

        Verifies that every dataclass field is present as a key in the YAML
        document — a missing field would otherwise silently fall back to the
        class default and drift from what the file claims to describe.
        """
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise TypeError(
                f"{path}: expected a YAML mapping at the document root, got {type(data).__name__}"
            )
        expected = {f.name for f in fields(cls)}
        missing = expected - data.keys()
        if missing:
            raise ValueError(f"{path}: missing required field(s): {', '.join(sorted(missing))}")
        unknown = data.keys() - expected
        if unknown:
            raise ValueError(f"{path}: unknown field(s): {', '.join(sorted(unknown))}")
        return cls(**data)

    def save(self, path: str | Path) -> None:
        """Write this theme to a YAML file."""
        path = Path(path)
        data: dict[str, Any] = {f.name: getattr(self, f.name) for f in fields(self)}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


_STATUS_FIELD_BY_STATUS: dict[GitStatus, Callable[[UITheme], str]] = {
    GitStatus.UNMODIFIED: lambda _t: "",
    GitStatus.MODIFIED: lambda t: t.status_modified,
    GitStatus.TYPE_CHANGED: lambda t: t.status_type_changed,
    GitStatus.ADDED: lambda t: t.status_added,
    GitStatus.DELETED: lambda t: t.status_deleted,
    GitStatus.RENAMED: lambda t: t.status_renamed,
    GitStatus.COPIED: lambda t: t.status_copied,
    GitStatus.UPDATED_UNMERGED: lambda t: t.status_unmerged,
    GitStatus.UNTRACKED: lambda t: t.status_untracked,
    GitStatus.IGNORED: lambda t: t.status_ignored,
}
