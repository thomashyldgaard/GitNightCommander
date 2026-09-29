"""Main Textual application for GitNightCommander."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import textwrap
import threading
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import IO, ClassVar, NamedTuple

from rich.text import Text
from textual import work
from textual.app import (
    App,
    ComposeResult,
    InvalidThemeError,
    ScreenStackError,
    SuspendNotSupported,
)
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import QueryError
from textual.message import Message
from textual.screen import ModalScreen
from textual.types import NoActiveAppError
from textual.widget import Widget
from textual.widgets import (
    Button,
    ContentSwitcher,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    OptionList,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

from .git import ANSI_SGR_PATTERN, GIT, Commit, GitCode, GitEntry, GitFilelist
from .terminal import Terminal, started_from_midnight_commander
from .themes import load_all as _load_all_themes
from .ui_theme import UITheme

# Raised when a widget asks for screen geometry before it is mounted, or with
# an empty screen stack. Every caller centres itself on the screen and falls
# back to a fixed offset, so losing the measurement is not an error.
NO_SCREEN_ERRORS = (NoActiveAppError, ScreenStackError)

# `query_one` raises QueryError when the widget genuinely isn't there. Before
# the app is mounted the lookup fails earlier still — there is no screen to
# search — so guard those two cases too. Every caller treats all three the
# same way: the widget isn't available, so skip the update.
WIDGET_LOOKUP_ERRORS = (QueryError, ScreenStackError, NoActiveAppError)

MODE_SHORT = "short"
MODE_LONG = "long"

# Quick filters for the file list, in the order `f` cycles through them, with
# the text the status line under the list shows for each. FILTER_NONE lists
# every file `git status` reports; FILTER_UNTRACKED_DIRS shows a directory
# holding nothing git has ever tracked as one `dir/` row instead of every file
# below it, which is what keeps a freshly unpacked tree from burying the
# changes that matter.
FILTER_NONE = "none"
FILTER_UNTRACKED_DIRS = "untracked-dirs"
FILE_LIST_FILTERS: list[str] = [FILTER_NONE, FILTER_UNTRACKED_DIRS]
FILE_LIST_FILTER_LABELS: dict[str, str] = {
    FILTER_NONE: "Filter: none",
    FILTER_UNTRACKED_DIRS: "Filter: untracked folders collapsed",
}

# Menu entries that belong to a mutually exclusive group carry a radio marker
# in a fixed-width gutter; every other entry pads that gutter with blanks so
# all labels start in the same column no matter which mode is active.
# Turbo Vision / Midnight Commander style accelerator marker: the character
# after it is the one highlighted in the menu and bound as its shortcut.
MENU_MNEMONIC_MARKER = "&"

MENU_RADIO_ON = "\u25cf"
MENU_RADIO_OFF = "\u25cb"
MENU_MARKER_BLANK = " "
MENU_MARKER_GAP = " "

# An entry that opens a nested menu instead of acting advertises it with a
# right-aligned arrow, in the same column the shortcut hints use.
MENU_SUBMENU_MARKER = "\u25b6"

SHORT_NAME_WIDTH = 25
LONG_NAME_WIDTH = 60
STATUS_WIDTH = 6
SIZE_WIDTH = 10
MTIME_WIDTH = 16
COLUMN_GAP = 2
STATUS_LIST_ITEM_HORIZONTAL_PADDING = 2


# Drafting a commit message shells out to whatever tool the user names in
# Options -> Settings. There is no default command — until one is filled in
# the Draft button just says so — but the prompt has a usable default, so
# naming the command is all the setup a tool needs.
COMMIT_DRAFT_COMMAND_DEFAULT = ""
COMMIT_DRAFT_PROMPT_DEFAULT = "Write a concise git commit message for these files:"
# The tool is typically an LLM CLI, so it gets minutes rather than seconds
# before the worker running it gives up.
COMMIT_DRAFT_TIMEOUT_SECONDS = 300
# The killed process closes its pipes, so the stderr reader is already on its
# way out by the time it is joined; the timeout only stops a wedged reader
# from taking the worker down with it.
COMMIT_DRAFT_JOIN_SECONDS = 5
# Rows of the tool's output shown under the message while it runs, and the
# number of lines kept — a chatty tool would otherwise grow the log without
# bound for output nobody scrolls back to.
COMMIT_DRAFT_OUTPUT_ROWS = 6
COMMIT_DRAFT_OUTPUT_LINES = 200
# Asked at startup under Midnight Commander, which reads the keyboard itself
# and forwards it to its subshell, keeping Ctrl+O for its own panels.
MIDNIGHT_COMMANDER_WARNING_TITLE = "Started from Midnight Commander"
MIDNIGHT_COMMANDER_WARNING = (
    "mc sees the keyboard before this app does. Ctrl+O switches back to mc's "
    "panels instead of the previous screen, and other shortcuts may reach the "
    "wrong app and behave unpredictably."
)
# Wide enough for the warning to wrap into a few readable lines.
MIDNIGHT_COMMANDER_DIALOG_WIDTH = 60
# Asked at startup when the repository is a submodule, however deeply nested:
# the question is always about the outermost repository.
SUPERPROJECT_PROMPT = "This repository is a submodule. Start in the top-level repository?"

# Where the commit message is written: the app's own dialog, the editor named
# by $EDITOR, or a command line typed into Options -> Settings. The last two
# edit a temporary file on the previous screen.
COMMIT_EDITOR_BUILTIN = "builtin"
COMMIT_EDITOR_ENVIRONMENT = "environment"
COMMIT_EDITOR_COMMAND = "command"
COMMIT_EDITOR_MODES = (COMMIT_EDITOR_BUILTIN, COMMIT_EDITOR_ENVIRONMENT, COMMIT_EDITOR_COMMAND)
# The temporary file's name is git's own, which is what tells vim, Emacs and
# VS Code to open it in their git-commit mode.
COMMIT_EDITOR_FILENAME = "COMMIT_EDITMSG"
# Git's `--cleanup=scissors` marker: everything from it down is the help text
# and the file list, and nothing above it is dropped — so a message line that
# starts with `#` (an issue number, say) survives, as it would not if every
# `#` line were read as a comment.
COMMIT_EDITOR_SCISSORS = "# ------------------------ >8 ------------------------"
# Rows the suggestion picker shows before it starts scrolling. A tool asked
# for a handful of messages rarely returns more.
SUGGESTION_DIALOG_MAX_ROWS = 12

DEFAULT_BRANCH_DEFAULT = "master"

# Top-level menus: (label, widget id). The "&" marks the accelerator letter,
# highlighted in the bar and opened with Alt+that letter.
MENU_BAR: list[tuple[str, str]] = [
    ("&File", "menu_file"),
    ("&Repo", "menu_repo"),
    ("&View", "menu_view"),
    ("&Options", "menu_options"),
    ("&Help", "menu_help"),
]

# Whole-repository commands. They are their own menu rather than more entries
# under File, which is about the file under the cursor (plus Refresh and
# Quit); pull, push and stash act on the repo no matter what is highlighted.
REPO_MENU: list[tuple[str, str]] = [
    ("&Pull", "pull"),
    ("P&ush", "push"),
    ("&Stash", "stash"),
    ("Stash p&op", "stash_pop"),
]

VIEW_MENU: list[tuple[str, str]] = [
    ("&Status", "view_status"),
    ("&History", "view_history"),
]

MIDNIGHT_COMMANDER_THEME_NAME = "midnight-commander"

THEMES: list[UITheme] = _load_all_themes()
_UI_THEMES_BY_NAME: dict[str, UITheme] = {theme.name: theme for theme in THEMES}
MIDNIGHT_COMMANDER_THEME: UITheme = _UI_THEMES_BY_NAME[MIDNIGHT_COMMANDER_THEME_NAME]
THEME_MENU: list[tuple[str, str]] = [(theme.name, f"set_theme('{theme.name}')") for theme in THEMES]


@dataclass(frozen=True)
class Submenu:
    """A nested menu: entries that open another dropdown instead of acting.

    One entry in `SUBMENUS` is all a nested menu needs. It names the dropdown
    that `GitNightCommanderApp.compose` mounts, the action that opens it, and the
    menu-bar label of the parent it cascades out of — and, because
    `MENU_SUBMENU_ACTIONS` is derived from the registry, the arrow marker the
    parent entry shows appears without a second place to update.
    """

    name: str
    items: list[tuple[str, str]]
    parent_id: str

    @property
    def dropdown_id(self) -> str:
        """The id of the `DropdownMenu` widget holding this menu's entries."""
        return f"dropdown_{self.name}"

    @property
    def action(self) -> str:
        """What the parent menu's entry runs to open this menu."""
        return f"open_submenu('{self.name}')"


SUBMENUS: list[Submenu] = [
    Submenu(name="theme", items=THEME_MENU, parent_id="menu_options"),
]
SUBMENUS_BY_NAME: dict[str, Submenu] = {submenu.name: submenu for submenu in SUBMENUS}


OPTIONS_MENU: list[tuple[str, str]] = [
    ("&Theme", SUBMENUS_BY_NAME["theme"].action),
    ("&Settings", "settings"),
]

HELP_MENU: list[tuple[str, str]] = [
    ("&Keys", "keys"),
]


# (key, action_name, footer_description, show_in_footer)
#
# Two key shapes, split by what the action is about. Function keys are the
# file-manager verbs every TUI in this lineage has put on that row (F3 view,
# F5 refresh, F7/F8 restore and delete) plus the chrome (F9 menu, F10 quit);
# bare letters are the git verbs — stage, unstage, commit, and now the repo
# commands. Within a letter pair, shift is the counterpart: `p` pulls and `P`
# pushes, `z` stashes and `Z` pops. The four new ones are `show=False`
# deliberately: the footer already runs past 80 columns with eleven entries,
# and they are advertised in the Repo menu and Help -> Keys instead.
SHORTCUTS: list[tuple[str, str, str, bool]] = [
    ("f10", "quit", "Quit", True),
    ("f5", "refresh", "Refresh", True),
    ("ctrl+o", "toggle_previous_screen", "Prev Screen", True),
    ("f3", "toggle_file_list", "Short/long list", True),
    ("f", "toggle_file_filter", "Filter", False),
    ("s", "stage_file", "Stage", True),
    ("u", "unstage_file", "Unstage", True),
    ("f7", "restore_file", "Restore", True),
    ("f8", "delete_file", "Delete", True),
    ("c", "commit_files", "Commit", True),
    ("p", "pull", "Pull", False),
    ("P", "push", "Push", False),
    ("z", "stash", "Stash", False),
    ("Z", "stash_pop", "Stash pop", False),
    ("ctrl+u", "clear_selection", "Clear selection", True),
    ("f9", "open_menu", "Menu", True),
    ("f1", "keys", "Keys", False),
    ("escape", "escape", "Back / close", False),
]

# (key, action_name) — extra keys reaching an action SHORTCUTS already lists.
# The primary key is the one the footer, the menu hints and the app's own
# docs advertise; an alias only has to work. Delete carries both because the
# function-key row is the one every TUI file manager has used since Norton
# Commander, while the dedicated Del key is missing from many laptops.
# Commit carries F2 because that is the key that submits the message inside
# the dialog, so the same key opens and closes the flow.
# Quit carries `q` because F10 is not ours to rely on: a terminal emulator
# can keep it for itself — VS Code's integrated terminal hands it to the
# debugger's Step Over and never forwards it — and a key the app never
# receives looks exactly like an app that ignores it. A bare letter always
# arrives. It stays out of the priority binding F10 has, so unlike F10 it
# cannot fire from inside a dialog: `q` there is someone typing a commit
# message.
SHORTCUT_ALIASES: list[tuple[str, str]] = [
    ("delete", "delete_file"),
    ("f2", "commit_files"),
    ("q", "quit"),
]


# Keys whose Textual name reads badly in a menu hint column.
MENU_KEY_NAMES: dict[str, str] = {
    "delete": "Del",
    "escape": "Esc",
    "ctrl": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
}

# Gap between a dropdown label and its right-aligned shortcut hint.
MENU_HINT_GAP = 2


def _is_shifted_letter(key: str) -> bool:
    """True for a shift+letter binding, which Textual names by the letter.

    `Key.key` for shift+P is just `"P"`, so an uppercase single character is
    the whole of what distinguishes it from `p` — one cell apart in a hint
    column, which is why both places that render a key spell it out.
    """
    return len(key) == 1 and key.isupper()


def _format_shortcut_key(key: str) -> str:
    """Render a Textual key name the way a menu hint column shows it."""
    if _is_shifted_letter(key):
        return f"Shift+{key}"
    return "+".join(MENU_KEY_NAMES.get(part, part.upper()) for part in key.split("+"))


def _shortcut_key_display(key: str) -> str | None:
    """`F10` for a function key, `Shift+P` for a shifted letter, else None.

    Textual names function keys in lower case (`f10`) and shows that name
    verbatim, and it shows a shift+letter as the bare uppercase letter — the
    two places a shortcut would read differently from the menu hint column
    and from every label in the app. None means "no override", so Textual
    keeps its own display for the rest — `^o` for `ctrl+o`, which reads
    better than spelling the modifier out.
    """
    if re.fullmatch(r"f\d+", key):
        return key.upper()
    if _is_shifted_letter(key):
        return f"Shift+{key}"
    return None


# Shortcut hint per action, so a dropdown entry advertises the same key the
# footer does without the menu tables repeating it. Aliases stay out of it:
# the hint column has room for one key, and it shows the primary one.
MENU_HINTS_BY_ACTION: dict[str, str] = {
    action: _format_shortcut_key(key) for key, action, _, _ in SHORTCUTS
}

# Footer description per action, so an alias binding describes itself the same
# way the primary key does.
SHORTCUT_DESCRIPTIONS_BY_ACTION: dict[str, str] = {
    action: description for _, action, description, _ in SHORTCUTS
}

# Alias keys per action, in table order, for the one place that lists every
# way to reach an action: the help dialog.
ALIAS_KEYS_BY_ACTION: dict[str, list[str]] = {}
for _alias_key, _alias_action in SHORTCUT_ALIASES:
    ALIAS_KEYS_BY_ACTION.setdefault(_alias_action, []).append(_alias_key)

# SHORTCUTS with each action's aliases folded into the key column, function
# keys and shifted letters spelled the same way the footer and the menu hints
# show them.
HELP_SHORTCUTS: list[tuple[str, str, str, bool]] = [
    (
        ", ".join(
            _shortcut_key_display(k) or k for k in [key, *ALIAS_KEYS_BY_ACTION.get(action, [])]
        ),
        action,
        description,
        show,
    )
    for key, action, description, show in SHORTCUTS
]

# Actions that open a nested menu rather than doing something. They carry the
# submenu arrow where a leaf entry would carry its shortcut hint. Derived from
# the registry, so registering a submenu is what marks its parent entry.
MENU_SUBMENU_ACTIONS: frozenset[str] = frozenset(submenu.action for submenu in SUBMENUS)


def _dropdown_id(menu_id: str) -> str:
    """The id of the dropdown belonging to the menu-bar label *menu_id*."""
    return menu_id.replace("menu_", "dropdown_")


def _split_mnemonic(label: str) -> tuple[str, int]:
    """Split *label* into its plain text and the accelerator character index.

    Menu labels mark their accelerator Turbo Vision style, with a marker in
    front of one character ("&File"). The marker never reaches the screen: it
    is stripped here, and the index it leaves behind says which character the
    renderer highlights and which key selects the entry. A doubled marker
    ("&&") escapes to a literal one. Labels without a marker get index -1.
    """
    plain: list[str] = []
    index = -1
    position = 0
    while position < len(label):
        char = label[position]
        if char != MENU_MNEMONIC_MARKER or position + 1 >= len(label):
            plain.append(char)
            position += 1
            continue
        marked = label[position + 1]
        if marked != MENU_MNEMONIC_MARKER and index == -1:
            index = len(plain)
        plain.append(marked)
        position += 2
    return "".join(plain), index


def _menu_plain_label(label: str) -> str:
    """*label* as the user sees it, with the accelerator markers removed."""
    return _split_mnemonic(label)[0]


def _menu_mnemonic_key(label: str) -> str | None:
    """The lower-case key that selects *label*, or None when it marks none."""
    plain, index = _split_mnemonic(label)
    return plain[index].lower() if index >= 0 else None


def _mnemonic_markup(text: str, index: int, *, style: str) -> str:
    """Wrap the character at *index* of *text* in *style*, as content markup."""
    if index < 0:
        return text
    return f"{text[:index]}[{style}]{text[index]}[/]{text[index + 1 :]}"


def _menu_mnemonic_style(widget: Widget) -> str:
    """The active theme's accelerator style, with a fallback for no live app.

    Menu chrome renders while composing, which in tests happens before the
    widget is wired up to an app.
    """
    try:
        return widget.app._active_ui_theme().menu_mnemonic  # pyright: ignore[reportAttributeAccessIssue]
    except NO_SCREEN_ERRORS:
        return MIDNIGHT_COMMANDER_THEME.menu_mnemonic


def _menu_hint(action: str) -> str:
    """What *action* shows in a dropdown's right-hand column.

    An entry that opens a nested menu gets the submenu arrow, so the user can
    tell it apart from a leaf entry; everything else gets its shortcut key, if
    it has one.
    """
    if action in MENU_SUBMENU_ACTIONS:
        return MENU_SUBMENU_MARKER
    return MENU_HINTS_BY_ACTION.get(action, "")


def _menu_option_labels(items: list[tuple[str, str]]) -> list[str]:
    """Pad *items*' labels so their right-hand column lines up on the edge.

    Accelerator markers are stripped, so the widths are the ones the user
    sees. Items with neither a shortcut nor a submenu arrow still get the
    padding, so every label in the menu occupies the same width and the
    column stays straight.
    """
    labels = [_menu_plain_label(label) for label, _ in items]
    hints = [_menu_hint(action) for _, action in items]
    hint_width = max((len(hint) for hint in hints), default=0)
    if not hint_width:
        return labels
    label_width = max(len(label) for label in labels)
    return [
        f"{label:<{label_width}}{' ' * MENU_HINT_GAP}{hint:>{hint_width}}"
        for label, hint in zip(labels, hints)
    ]


def _menu_option_markup(items: list[tuple[str, str]], *, style: str) -> list[str]:
    """`_menu_option_labels`, with each accelerator letter highlighted.

    The marker is stripped before the label is padded, and the padding is
    appended, so an accelerator's index in the padded label is the one
    `_split_mnemonic` reported for the raw label.
    """
    return [
        _mnemonic_markup(padded, _split_mnemonic(label)[1], style=style)
        for padded, (label, _) in zip(_menu_option_labels(items), items)
    ]


class MenuLabel(Static):
    """A clickable label used as a top-level menu item in the MenuBar.

    Takes its text with an accelerator marker ("&File") and renders the
    marked character in the theme's accelerator style, so the bar advertises
    the Alt+letter that opens it.
    """

    DEFAULT_CSS = """
    MenuLabel {
        padding: 0 1;
        height: 1;
        width: auto;
        color: $menu-bar-foreground;
    }
    /* Hover tints the bar with its own text color and the open menu reverses
       it, so both states are derived from the two chrome colors a theme sets
       and stay legible whatever those are. */
    MenuLabel:hover {
        background: $menu-bar-foreground 15%;
        color: $menu-bar-foreground;
    }
    MenuLabel.-active {
        background: $menu-bar-foreground;
        color: $menu-bar-background;
    }
    """

    class Pressed(Message):
        def __init__(self, label: MenuLabel) -> None:
            super().__init__()
            self.label = label

    def __init__(self, label: str, **kwargs) -> None:
        self._plain, self._mnemonic_index = _split_mnemonic(label)
        # The styled text needs the app's theme, which is only reachable once
        # mounted; until then the label reads as plain text.
        super().__init__(self._plain, **kwargs)

    @property
    def mnemonic(self) -> str | None:
        """The lower-case key that opens this menu, or None."""
        return self._plain[self._mnemonic_index].lower() if self._mnemonic_index >= 0 else None

    def apply_mnemonic_style(self) -> None:
        """Re-render the label in the active theme's accelerator style."""
        self.update(
            _mnemonic_markup(
                self._plain,
                self._mnemonic_index,
                style=_menu_mnemonic_style(self),
            )
        )

    def on_mount(self) -> None:
        self.apply_mnemonic_style()

    def on_click(self) -> None:
        self.post_message(self.Pressed(self))


class MenuBar(Widget):
    """Horizontal bar docked at the top holding File, View and Options menus."""

    DEFAULT_CSS = """
    MenuBar {
        height: 1;
        dock: top;
        layout: horizontal;
        background: $menu-bar-background;
        color: $menu-bar-foreground;
    }
    """

    def compose(self) -> ComposeResult:
        for label, menu_id in MENU_BAR:
            yield MenuLabel(label, id=menu_id)

    def on_menu_label_pressed(self, event: MenuLabel.Pressed) -> None:
        label = event.label
        region = label.region
        self.app.toggle_menu(label.id, region.x, region.y + 1)  # type: ignore[arg-type]


class DropdownMenu(Widget):
    """Floating dropdown rendered on the overlay layer."""

    DEFAULT_CSS = """
    DropdownMenu {
        layer: overlay;
        /* `show_at` places menus in screen cells, so the offset has to be
           read from the container's origin. Without this a menu shown next
           to another one — a cascading submenu — starts after its visible
           siblings instead of where it was put. */
        position: absolute;
        display: none;
        background: $panel;
        border: solid $accent;
        width: auto;
        min-width: 0;
        height: auto;
        padding: 0;
    }
    DropdownMenu OptionList {
        width: 1fr;
        height: auto;
        border: none;
        background: transparent;
        padding: 0;
    }
    DropdownMenu OptionList:focus {
        border: none;
        outline: none;
    }
    """

    def __init__(self, items: list[tuple[str, str]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._items = items

    def compose(self) -> ComposeResult:
        yield OptionList(*[Option(label) for label in self._option_markup()])

    def _option_markup(self) -> list[str]:
        return _menu_option_markup(self._items, style=_menu_mnemonic_style(self))

    def _render_options(self) -> None:
        try:
            option_list = self.query_one(OptionList)
        except WIDGET_LOOKUP_ERRORS:
            return
        option_list.clear_options()
        for label in self._option_markup():
            option_list.add_option(Option(label))

    def set_items(self, items: list[tuple[str, str]]) -> None:
        self._items = items
        self._render_options()

    def apply_mnemonic_style(self) -> None:
        """Re-render the entries in the active theme's accelerator style."""
        self._render_options()

    @property
    def menu_width(self) -> int:
        """How wide this menu renders, border included.

        Computed from the items rather than read back from the layout, so a
        menu can be placed against another one that Textual has not laid out
        yet (a cascading submenu opens in the same tick as its parent).
        """
        return max(len(label) for label in _menu_option_labels(self._items)) + 4

    def index_of_action(self, action: str) -> int | None:
        """The row *action* sits on, or None when this menu doesn't run it."""
        return next((i for i, (_, item) in enumerate(self._items) if item == action), None)

    def highlight_action(self, action: str) -> None:
        """Put the cursor on the entry that runs *action*, if there is one.

        Used when a nested menu closes back to its parent, so the cursor
        lands on the entry the user opened it from instead of the top.
        """
        index = self.index_of_action(action)
        if index is None:
            return
        try:
            option_list = self.query_one(OptionList)
        except WIDGET_LOOKUP_ERRORS:
            return
        option_list.highlighted = index

    def action_for_mnemonic(self, char: str) -> str | None:
        """The action of the entry whose accelerator is *char*, if any."""
        for label, action in self._items:
            if _menu_mnemonic_key(label) == char.lower():
                return action
        return None

    async def _run_menu_action(self, action: str) -> None:
        self.display = False
        await self.app.run_action(action)

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        await self._run_menu_action(self._items[event.option_index][1])

    async def on_key(self, event) -> None:
        """Run the entry whose highlighted letter was typed.

        Any other bare character is swallowed rather than passed on: while a
        menu is open the app's single-letter bindings (`s`, `u`, `c`) must not
        fire behind it. Only keys whose name *is* their character are claimed,
        which leaves `space` and `enter` to the OptionList's own selection
        handling and lets `alt+letter` bubble up to the menu bar.
        """
        char = event.character
        if not char or event.key != char:
            return
        event.stop()
        event.prevent_default()
        action = self.action_for_mnemonic(char)
        if action is not None:
            await self._run_menu_action(action)

    def show_at(self, x: int, y: int) -> None:
        self.styles.width = self.menu_width
        self.styles.offset = (x, y)
        self.display = True
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None:
            # A menu opens with its cursor on the first entry: an open menu
            # with no visible cursor gives the user nothing to navigate from.
            option_list.highlighted = 0
        _ = self.app.set_focus(option_list)

    def hide(self) -> None:
        self.display = False


CONFIRM_DIALOG_MAX_COMMAND_ROWS = 10
# The commands area spends its first and last row on `padding: 1 0`.
CONFIRM_DIALOG_COMMANDS_PADDING_HEIGHT = 2
# So this many commands fit before it starts scrolling.
CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS = (
    CONFIRM_DIALOG_MAX_COMMAND_ROWS - CONFIRM_DIALOG_COMMANDS_PADDING_HEIGHT
)
# `border: solid` (1 row top and bottom) plus `padding: 1 2` (1 row top and
# bottom) plus the prompt and hint rows: what the popup spends on everything
# but the commands area, vertically.
CONFIRM_DIALOG_CHROME_HEIGHT = 6
# `border: solid` (1 cell each side) plus `padding: 1 2` (2 cells each side):
# what the popup spends on chrome, i.e. how much narrower its text is than the
# box that holds it.
CONFIRM_DIALOG_CHROME_WIDTH = 6
# Width of the commands area's scrollbar. Pinned in the dialog's own CSS so
# the reservation below can't drift from what Textual actually draws.
CONFIRM_DIALOG_SCROLLBAR_WIDTH = 2
# A dialog narrower than this is unreadable no matter how short its file list
# is, so the prompt/hint set the floor rather than the widest command.
CONFIRM_DIALOG_MIN_TEXT_WIDTH = 30
# Appended in place of the cut-off tail of a line that doesn't fit the screen.
TRUNCATION_MARKER = "…"
SETTINGS_FILENAME = "settings.json"


def _strip_markup(text: str) -> str:
    """`text` without its content-markup tags, i.e. what it occupies on screen."""
    return re.sub(r"\[/?[^\[\]]*\]", "", text)


def _escape_markup(text: str) -> str:
    """`text` rendered literally, i.e. with its markup tags neutralised.

    Settings values are typed by the user and drawn into a markup-rendering
    Static, so a prompt template mentioning "[files]" would otherwise be read
    as a style tag and swallowed.
    """
    return text.replace("[", "\\[")


# One word of a settings field plus the spaces that follow it, or a run of
# spaces on its own — the units `_wrap_field_text()` moves between lines.
FIELD_WRAP_TOKEN_PATTERN = re.compile(r"\S+ *| +")


class FieldLine(NamedTuple):
    """One display line of a framed field: the text on it, and where that text
    starts in the value it was wrapped from.

    The offset is what lets the caret be a position in the value and a cell on
    the screen at the same time — `_caret_position()` maps one to the other.
    """

    start: int
    text: str


def _wrap_field_text(text: str, *, width: int) -> list[FieldLine]:
    """`text` broken at spaces into lines of at most `width` cells.

    Not `textwrap.wrap()`: this text is being typed into, so the space after
    a finished word has to survive — it is what pushes the caret along — and
    an empty value has to come back as one empty line rather than no lines at
    all, or the field would have nothing to draw. A word longer than the
    field, a URL or a path, is broken where it fills the line, there being
    nowhere better to break it. Existing newlines start a new line, so a
    template saved with them keeps its shape.
    """
    lines: list[FieldLine] = []
    offset = 0
    for paragraph in text.split("\n"):
        current = ""
        start = offset
        for token in FIELD_WRAP_TOKEN_PATTERN.findall(paragraph):
            if current and len(current) + len(token) > width:
                lines.append(FieldLine(start=start, text=current))
                start += len(current)
                current = token
            else:
                current += token
            while len(current) > width:
                lines.append(FieldLine(start=start, text=current[:width]))
                start += width
                current = current[width:]
        lines.append(FieldLine(start=start, text=current))
        # Past the end of this line sits the newline that ended the paragraph.
        offset = start + len(current) + 1
    return lines


def _caret_position(lines: list[FieldLine], *, caret: int) -> tuple[int, int]:
    """Where offset `caret` falls in `lines`, as (line index, column).

    The last line starting at or before the caret: on a wrap boundary the two
    lines share the offset, and the caret belongs to the one it is about to
    type into rather than the one it just filled.
    """
    row = 0
    for index, line in enumerate(lines):
        if line.start > caret:
            break
        row = index
    return row, min(caret - lines[row].start, len(lines[row].text))


def _caret_markup(text: str, *, column: int, style: str) -> str:
    """`text` with the cell at `column` marked as the caret.

    The caret sits *on* a cell rather than after the text, which is what lets
    it be positioned inside the value; past the last character it takes the
    blank that follows. The style has to swap the cell's colors rather than
    paint one, since it covers a character that still has to be readable.
    """
    head, cell, tail = text[:column], text[column : column + 1] or " ", text[column + 1 :]
    return f"{_escape_markup(head)}[{style}]{_escape_markup(cell)}[/{style}]{_escape_markup(tail)}"


def _setting_str(settings: Mapping[str, object], key: str, default: str) -> str:
    """`settings[key]` when it holds a string, else `default`.

    Settings come off disk as JSON, so a hand-edited file can put anything at
    all under any key.
    """
    value = settings.get(key, default)
    return value if isinstance(value, str) else default


def _truncate_to_width(text: str, width: int) -> str:
    """`text` cut down to `width` cells, with the cut marked as such.

    A file list is only useful if the reader can tell a name they are seeing
    in full from one that runs off the edge, so the marker replaces the last
    cells rather than being appended past the limit.
    """
    if width <= 0 or len(text) <= width:
        return text
    if width <= len(TRUNCATION_MARKER):
        return TRUNCATION_MARKER[:width]
    return text[: width - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


# How much of a `git stash list` line the pop confirmation quotes. The line
# carries the branch and the commit subject the entry was made on, which is
# what tells two entries apart; the rest can go, and the dialog only sizes
# itself from the commands and the hint anyway.
STASH_PROMPT_MAX_WIDTH = 60


# What stands in for a branch name on either side of a mismatch when the
# repository is on a detached HEAD and there is no name to print.
DETACHED_HEAD_LABEL = "(detached HEAD)"


def _submodule_mismatch_text(
    sub_path: str,
    sub_branch: str | None,
    parent_branch: str | None,
) -> str:
    """One line stating that a submodule is on a branch of its own.

    Shared by the status view's warning label and the pull/push
    confirmations, so the same fact can't be worded two ways depending on
    where it is read.
    """
    sub = sub_branch if sub_branch is not None else DETACHED_HEAD_LABEL
    parent = parent_branch if parent_branch is not None else DETACHED_HEAD_LABEL
    return f"submodule '{sub_path}' is on branch '{sub}' but parent is on '{parent}'"


def _remote_result_summary(result: subprocess.CompletedProcess[str], *, failed: bool) -> str:
    """The one line worth notifying about a finished pull or push.

    Which end of the output that is depends on how it went. A failure leads
    with the reason and follows it with git's hints ("! [rejected] …" and
    then three lines of advice), so the first stderr line is the message. A
    success ends with the outcome — "Already up to date.", "Everything
    up-to-date", the ref update — so the last line of either stream is.
    """
    stderr = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
    if failed:
        return stderr[0] if stderr else ""
    stdout = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    lines = stdout + stderr
    return lines[-1] if lines else ""


SCROLL_KEYS = ("up", "down", "pageup", "pagedown", "home", "end")


class SettingsValues(NamedTuple):
    """What the settings dialog hands back when the user saves."""

    branch_prefix: bool
    draft_command: str
    draft_prompt: str
    default_branch: str
    parse_suggestions: bool = False
    editor: str = COMMIT_EDITOR_BUILTIN
    editor_command: str = ""


# Rows of the settings dialog, in the order they are drawn. The checkbox rows
# are toggled with Space, and the three editor rows are a radio group Space
# picks from; every other row is a free-text field, edited a character at a
# time. The last three are the commit-drafting settings, drawn under the
# Experimental heading.
SETTINGS_ROW_BRANCH = 0
SETTINGS_ROW_PREFIX = 1
SETTINGS_ROW_EDITOR_BUILTIN = 2
SETTINGS_ROW_EDITOR_ENVIRONMENT = 3
SETTINGS_ROW_EDITOR_COMMAND = 4
SETTINGS_ROW_EDITOR_COMMAND_LINE = 5
SETTINGS_ROW_COMMAND = 6
SETTINGS_ROW_PROMPT = 7
SETTINGS_ROW_PARSE = 8
SETTINGS_ROW_COUNT = 9

# Which editor each radio row selects.
SETTINGS_EDITOR_ROWS: dict[int, str] = {
    SETTINGS_ROW_EDITOR_BUILTIN: COMMIT_EDITOR_BUILTIN,
    SETTINGS_ROW_EDITOR_ENVIRONMENT: COMMIT_EDITOR_ENVIRONMENT,
    SETTINGS_ROW_EDITOR_COMMAND: COMMIT_EDITOR_COMMAND,
}

# Inner width of the framed field the drafting prompt is edited in. It fits
# inside `SettingsDialog`'s `min-width: 72` box with its indent and border,
# so the frame never widens the dialog. One of those cells is the space that
# keeps the text off the left border, leaving the rest for the text itself.
SETTINGS_FIELD_WIDTH = 60
SETTINGS_FIELD_TEXT_WIDTH = SETTINGS_FIELD_WIDTH - 1

# How tall that field is: this many lines when the value is shorter, then one
# line per wrapped line until the cap, past which the field scrolls. The cap
# is what keeps a pasted-in essay from pushing the rows below it off screen.
SETTINGS_FIELD_MIN_LINES = 3
SETTINGS_FIELD_MAX_LINES = 8

# How far a section heading's rule runs: to the right edge of the framed
# field, which is the widest thing the dialog draws (its four-cell indent
# plus the frame's two borders).
SETTINGS_SECTION_WIDTH = 4 + SETTINGS_FIELD_WIDTH + 2


def _dialog_theme(screen: ModalScreen) -> UITheme:
    """The active UITheme, falling back when there is no live app.

    Dialogs render themed markup while composing, which happens before the
    screen is fully wired up in some tests.
    """
    try:
        return screen.app._active_ui_theme()  # pyright: ignore[reportAttributeAccessIssue]
    except NO_SCREEN_ERRORS:
        return MIDNIGHT_COMMANDER_THEME


class ConfirmDialog(ModalScreen[bool]):
    """Modal confirmation dialog.

    Shows a prompt, one or more git commands that will run, and a Y/N hint.
    When more commands are supplied than fit in the popup, the command list
    becomes scrollable.

    The box is as wide as the file list it shows — the widest of the prompt,
    the commands and the hint — and stops at the screen edge, where a command
    too long to fit is cut with `TRUNCATION_MARKER` so a name running off the
    end can be told from one shown in full.

    As a ModalScreen it truncates Textual's binding chain (see
    `Screen._modal_binding_chain`), so the file list underneath keeps neither
    focus nor bindings — no key handled here can leak into an app action, and
    no app action can re-enter while it is open.

    With `fill_height` the command list is not capped at
    `CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS` but grows to the screen height, so a
    commit's whole file list can be read without scrolling when it fits.
    """

    # The screen itself handles every key, so nothing inside should take
    # focus; leaving this as None also stops the app's "#status_list"
    # AUTO_FOCUS from being applied to this screen.
    AUTO_FOCUS = None

    DEFAULT_CSS = f"""
    ConfirmDialog {{
        align: center middle;
    }}
    ConfirmDialog #confirm-body {{
        background: $panel;
        border: solid $accent;
        width: auto;
        max-width: 100%;
        height: auto;
        padding: 1 2;
    }}
    ConfirmDialog Label {{
        width: 100%;
        height: auto;
    }}
    ConfirmDialog #confirm-commands {{
        width: auto;
        height: auto;
        max-height: {CONFIRM_DIALOG_MAX_COMMAND_ROWS};
        padding: 1 0;
        background: transparent;
        scrollbar-size-vertical: {CONFIRM_DIALOG_SCROLLBAR_WIDTH};
    }}
    ConfirmDialog #confirm-commands-content {{
        width: auto;
        height: auto;
        color: $accent;
    }}
    """

    def __init__(self, prompt: str, commands: list[str], *, fill_height: bool = False) -> None:
        super().__init__()
        self.prompt = prompt
        self.commands = list(commands)
        self.fill_height = fill_height

    def compose(self) -> ComposeResult:
        theme = _dialog_theme(self)
        hint = (
            f"[{theme.confirm_yes_key}]Y[/]es   "
            f"[{theme.confirm_no_key}]N[/]o   "
            f"[{theme.dialog_hint}](↑↓ scroll, Esc cancels)[/{theme.dialog_hint}]"
        )
        text_width = self.text_width(hint=_strip_markup(hint))
        body = Vertical(id="confirm-body")
        if text_width:
            # The box is sized from its content instead of left on `width:
            # auto` so the file list decides the width up to the screen edge,
            # and so the truncation below is measured against the same number.
            body.styles.width = text_width + CONFIRM_DIALOG_CHROME_WIDTH + self.scrollbar_width()
        with body:
            yield Label(self.prompt, id="confirm-prompt")
            commands_area = ScrollableContainer(id="confirm-commands")
            if self.fill_height:
                commands_area.styles.max_height = (
                    self.visible_command_rows() + CONFIRM_DIALOG_COMMANDS_PADDING_HEIGHT
                )
            with commands_area:
                yield Static(
                    "\n".join(self.command_lines(text_width)),
                    id="confirm-commands-content",
                )
            yield Label(hint, id="confirm-hint")

    def command_lines(self, width: int = 0) -> list[str]:
        """The command list as rendered, truncated to `width` (0 = no limit)."""
        return [_truncate_to_width(f"$ {cmd}", width) for cmd in self.commands]

    def text_width(self, *, hint: str = "") -> int:
        """Inner width of the popup: as wide as its widest line, but never
        wider than the screen. 0 when the screen hasn't been measured yet, in
        which case the CSS `width: auto` sizes the box instead.
        """
        available = self._available_text_width()
        if not available:
            return 0
        widest = max(len(line) for line in [self.prompt, hint, *self.command_lines()])
        return max(min(widest, available), min(CONFIRM_DIALOG_MIN_TEXT_WIDTH, available))

    def scrollbar_width(self) -> int:
        """Cells the commands area's scrollbar will take, 0 when it won't
        scroll. Sizing the box without it would push the scrollbar past the
        border, where it is clipped and the user never sees that there is
        more of the list below.
        """
        if len(self.commands) <= self.visible_command_rows():
            return 0
        return CONFIRM_DIALOG_SCROLLBAR_WIDTH

    def visible_command_rows(self) -> int:
        """How many commands show before the list scrolls: the CSS cap, or
        with `fill_height` whatever the screen has room for once the rest of
        the popup is drawn. An unmeasured screen falls back to the cap.
        """
        if not self.fill_height:
            return CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS
        try:
            screen_height = self.app.size.height
        except NO_SCREEN_ERRORS:
            return CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS
        if not screen_height:
            return CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS
        room = screen_height - CONFIRM_DIALOG_CHROME_HEIGHT - CONFIRM_DIALOG_COMMANDS_PADDING_HEIGHT
        return max(room, 1)

    def _available_text_width(self) -> int:
        """How much text the screen has room for, chrome subtracted."""
        try:
            screen_width = self.app.size.width
        except NO_SCREEN_ERRORS:
            return 0
        if not screen_width:
            return 0
        room = screen_width - CONFIRM_DIALOG_CHROME_WIDTH - self.scrollbar_width()
        return max(room, len(TRUNCATION_MARKER))

    def on_key(self, event) -> None:
        """Answer, scroll, or swallow. Every key stops here so none reaches
        the app's own on_key while the dialog is up."""
        event.stop()
        event.prevent_default()
        key = event.key
        if key in ("y", "Y", "enter"):
            self.dismiss(True)
        elif key in ("n", "N", "escape"):
            self.dismiss(False)
        elif key in SCROLL_KEYS:
            self.scroll_commands(key)

    def scroll_commands(self, direction: str) -> None:
        try:
            container = self.query_one("#confirm-commands", ScrollableContainer)
        except WIDGET_LOOKUP_ERRORS:
            return
        if direction == "up":
            container.scroll_up(animate=False)
        elif direction == "down":
            container.scroll_down(animate=False)
        elif direction == "pageup":
            container.scroll_page_up(animate=False)
        elif direction == "pagedown":
            container.scroll_page_down(animate=False)
        elif direction == "home":
            container.scroll_home(animate=False)
        elif direction == "end":
            container.scroll_end(animate=False)


class MidnightCommanderDialog(ModalScreen[bool]):
    """Startup warning when the app runs under Midnight Commander.

    Dismisses with True to continue and False to exit. Esc exits: the
    warning is about keys going astray, so the key that backs out of a
    question shouldn't be the one that carries on regardless.
    """

    AUTO_FOCUS = None

    DEFAULT_CSS = f"""
    MidnightCommanderDialog {{
        align: center middle;
    }}
    MidnightCommanderDialog #mc-warning-body {{
        background: $panel;
        border: solid $warning;
        border-title-color: $warning;
        border-title-style: bold;
        width: {MIDNIGHT_COMMANDER_DIALOG_WIDTH};
        max-width: 100%;
        height: auto;
        padding: 1 2;
    }}
    MidnightCommanderDialog Label {{
        width: 100%;
        height: auto;
    }}
    MidnightCommanderDialog #mc-warning-hint {{
        margin-top: 1;
    }}
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        theme = _dialog_theme(self)
        hint = (
            f"[{theme.confirm_yes_key}]C[/]ontinue   "
            f"[{theme.confirm_no_key}]E[/]xit   "
            f"[{theme.dialog_hint}](Esc exits)[/{theme.dialog_hint}]"
        )
        body = Vertical(id="mc-warning-body")
        body.border_title = MIDNIGHT_COMMANDER_WARNING_TITLE
        with body:
            yield Label(_escape_markup(self.message), id="mc-warning-message")
            yield Label(hint, id="mc-warning-hint")

    def on_key(self, event) -> None:
        """Answer or swallow; every key stops here, as in ConfirmDialog."""
        event.stop()
        event.prevent_default()
        key = event.key
        if key in ("c", "C", "enter"):
            self.dismiss(True)
        elif key in ("e", "E", "escape"):
            self.dismiss(False)


class HelpDialog(ModalScreen[None]):
    """Modal dialog listing the app's keyboard shortcuts."""

    AUTO_FOCUS = None

    DEFAULT_CSS = """
    HelpDialog {
        align: center middle;
    }
    HelpDialog #help-body {
        background: $panel;
        border: solid $accent;
        width: auto;
        max-width: 90%;
        height: auto;
        padding: 1 2;
    }
    HelpDialog Label {
        width: 100%;
        height: auto;
    }
    HelpDialog #help-content {
        width: auto;
        height: auto;
        padding: 1 0;
    }
    """

    def __init__(self, shortcuts: list[tuple[str, str, str, bool]]) -> None:
        super().__init__()
        self.shortcuts = list(shortcuts)

    def compose(self) -> ComposeResult:
        theme = _dialog_theme(self)
        key_width = max((len(k) for k, _, _, _ in self.shortcuts), default=0)
        body = "\n".join(f"{key:<{key_width}}  {desc}" for key, _, desc, _ in self.shortcuts)
        with Vertical(id="help-body"):
            yield Label("[b]Keyboard shortcuts[/b]", id="help-title")
            yield Static(body, id="help-content")
            yield Label(
                f"[{theme.dialog_hint}](Esc closes)[/{theme.dialog_hint}]",
                id="help-hint",
            )

    def on_key(self, event) -> None:
        """Esc/Enter close; everything else is swallowed so shortcuts listed
        here can't fire while the user is reading about them."""
        event.stop()
        event.prevent_default()
        if event.key in ("escape", "enter"):
            self.dismiss(None)


class SettingsDialog(ModalScreen["SettingsValues | None"]):
    """Modal settings dialog.

    Handles all its own keys — Tab and Space included — which as a modal
    screen no longer requires fighting the StatusList underneath or Textual's
    screen-level focus-cycling binding for them.

    Dismisses with the edited `SettingsValues` on Enter, or None on Escape.
    """

    AUTO_FOCUS = None

    DEFAULT_CSS = """
    SettingsDialog {
        align: center middle;
    }
    SettingsDialog #settings-body {
        background: $panel;
        border: solid $accent;
        width: auto;
        /* Wide enough for the framed prompt field and the section rules
           beside it (`SETTINGS_SECTION_WIDTH` plus this border and padding),
           which are the widest rows here — a narrower box wraps them, and
           `width: auto` can't grow past the widest child because that child
           is the full-width Static below. */
        min-width: 72;
        max-width: 90%;
        height: auto;
        padding: 1 2;
    }
    SettingsDialog Static {
        width: 100%;
        height: auto;
    }
    """

    # Which attribute each free-text row edits. Everything the key handler
    # and the renderer do to those rows is the same for all of them, so the
    # rows differ only by their label and the value they carry.
    TEXT_ROWS: ClassVar[dict[int, str]] = {
        SETTINGS_ROW_BRANCH: "_default_branch",
        SETTINGS_ROW_EDITOR_COMMAND_LINE: "_editor_command",
        SETTINGS_ROW_COMMAND: "_draft_command",
        SETTINGS_ROW_PROMPT: "_draft_prompt",
    }

    # The text rows drawn as a framed field rather than a value after a
    # label. Being several lines tall is what makes up and down the caret's
    # keys there instead of the row cursor's.
    FIELD_ROWS: ClassVar[frozenset[int]] = frozenset({SETTINGS_ROW_PROMPT})

    def __init__(
        self,
        branch_prefix: bool = False,
        draft_command: str = COMMIT_DRAFT_COMMAND_DEFAULT,
        draft_prompt: str = COMMIT_DRAFT_PROMPT_DEFAULT,
        default_branch: str = DEFAULT_BRANCH_DEFAULT,
        parse_suggestions: bool = False,
        editor: str = COMMIT_EDITOR_BUILTIN,
        editor_command: str = "",
    ) -> None:
        super().__init__()
        self._cursor: int = 0
        self._default_branch: str = default_branch
        self._branch_prefix: bool = branch_prefix
        self._draft_command: str = draft_command
        self._draft_prompt: str = draft_prompt
        self._parse_suggestions: bool = parse_suggestions
        self._editor: str = editor if editor in COMMIT_EDITOR_MODES else COMMIT_EDITOR_BUILTIN
        self._editor_command: str = editor_command
        # Where typing goes in the row under the cursor. A row is entered
        # with the caret after its last character, which is where a value
        # that is only ever appended to would have left it.
        self._caret: int = len(default_branch)

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-body"):
            yield Static("", id="settings-content")

    def on_mount(self) -> None:
        self._redraw()

    def on_key(self, event) -> None:
        """Every key the dialog receives, routed by the row under the cursor.

        Tab and Enter are what leave a row — Tab for the next one, Enter to
        save — so inside a framed field the arrows are free to be the caret's
        and never move off it. A one-line row has nowhere for up and down to
        go, so there they stay what they have always been: the row above and
        the row below.
        """
        key = event.key
        event.stop()
        event.prevent_default()
        if key == "shift+tab":
            self.move_cursor(-1)
        elif key == "tab":
            self.move_cursor(1)
        elif key == "enter":
            self.dismiss(self.get_values())
        elif key == "escape":
            self.dismiss(None)
        elif key in ("left", "right") and self._cursor in self.TEXT_ROWS:
            self.move_caret(-1 if key == "left" else 1)
        elif key in ("up", "down"):
            delta = -1 if key == "up" else 1
            if self._cursor in self.FIELD_ROWS:
                self.move_caret_line(delta)
            else:
                self.move_cursor(delta)
        elif self._cursor in self.TEXT_ROWS:
            self.edit_text(event)
        elif key == "space":
            self.toggle_current()

    def edit_text(self, event) -> None:
        """Apply one keystroke to the free-text row under the cursor.

        At the caret rather than at the end, since the caret is no longer
        always there — backspace takes the character in front of it, and
        anything typed pushes it along.
        """
        attribute = self.TEXT_ROWS[self._cursor]
        value: str = getattr(self, attribute)
        caret = self._clamped_caret(value)
        if event.key == "backspace":
            if not caret:
                return
            setattr(self, attribute, value[: caret - 1] + value[caret:])
            self._caret = caret - 1
        else:
            character = " " if event.key == "space" else getattr(event, "character", None)
            if not (isinstance(character, str) and character.isprintable() and len(character) == 1):
                return
            setattr(self, attribute, value[:caret] + character + value[caret:])
            self._caret = caret + 1
        if self._cursor == SETTINGS_ROW_EDITOR_COMMAND_LINE:
            # Typing a command is choosing to use it; making the user go back
            # up and pick the radio as well would only be a way to forget to.
            self._editor = COMMIT_EDITOR_COMMAND
        self._redraw()

    def _row_value(self) -> str:
        """The text of the row under the cursor, or "" on a checkbox row."""
        attribute = self.TEXT_ROWS.get(self._cursor)
        return getattr(self, attribute) if attribute is not None else ""

    def _clamped_caret(self, value: str) -> int:
        """The caret held inside `value`, which a row switch can leave it
        outside of until the next move."""
        return max(0, min(self._caret, len(value)))

    def move_caret(self, delta: int) -> None:
        """Move the caret one cell along the row being edited."""
        value = self._row_value()
        self._caret = max(0, min(len(value), self._clamped_caret(value) + delta))
        self._redraw()

    def move_caret_line(self, delta: int) -> None:
        """Move the caret one display line up or down inside a framed field.

        It keeps its column where the target line is long enough to hold it.
        The arrows never leave the field — Tab and Enter do that — so up from
        the first line and down from the last go to the two ends of the value
        instead of to the row above or below.
        """
        value = self._row_value()
        lines = _wrap_field_text(value, width=SETTINGS_FIELD_TEXT_WIDTH)
        row, column = _caret_position(lines, caret=self._clamped_caret(value))
        target = row + delta
        if target < 0:
            self._caret = 0
        elif target >= len(lines):
            self._caret = len(value)
        else:
            self._caret = lines[target].start + min(column, len(lines[target].text))
        self._redraw()

    def _text_row(self, row: int, label: str) -> str:
        """One free-text row: cursor arrow, label, value, and the caret on the
        row being edited."""
        value: str = getattr(self, self.TEXT_ROWS[row])
        if self._cursor != row:
            return f"  {label}{_escape_markup(value)}"
        caret = _caret_markup(
            value, column=self._clamped_caret(value), style=_dialog_theme(self).text_caret
        )
        return f"> {label}{caret}"

    def _section_header(self, title: str) -> str:
        """A heading with a rule running out to the width of the widest row,
        so the settings under it read as a group rather than as more of the
        list above."""
        theme = _dialog_theme(self)
        rule = "─" * max(0, SETTINGS_SECTION_WIDTH - len(title) - 1)
        return f"[b]{title}[/b] [{theme.dialog_hint}]{rule}[/{theme.dialog_hint}]"

    def _field_rows(self, row: int, label: str) -> list[str]:
        """A free-text row drawn as a framed input field, label above it.

        The drafting prompt is a paragraph, not a word, so it gets a field of
        its own instead of a value trailing its label: the frame marks where
        the text is whether or not the row is under the cursor, and the value
        wraps at word boundaries across as many lines as it needs rather than
        scrolling through one — a template is read as a whole, and its tail
        alone says little about what it asks for.

        The field is `SETTINGS_FIELD_MIN_LINES` tall while the value is
        shorter than that and grows with it up to `SETTINGS_FIELD_MAX_LINES`;
        only past the cap does it scroll, far enough to keep the caret's line
        on screen wherever the arrows have put it.
        """
        theme = _dialog_theme(self)
        value: str = getattr(self, self.TEXT_ROWS[row])
        focused = self._cursor == row
        width = SETTINGS_FIELD_TEXT_WIDTH
        lines = _wrap_field_text(value, width=width)
        caret = self._clamped_caret(value) if focused else None
        if caret is not None:
            if caret == len(value) and len(lines[-1].text) >= width:
                # Nothing to sit on: the value ends in the last cell of a
                # full line, so the caret takes the first cell of the next.
                lines.append(FieldLine(start=caret, text=""))
            caret_line, caret_column = _caret_position(lines, caret=caret)
        else:
            caret_line, caret_column = -1, -1
        height = min(max(len(lines), SETTINGS_FIELD_MIN_LINES), SETTINGS_FIELD_MAX_LINES)
        # Short of the height the blank lines go under the text; over it the
        # last lines are the ones kept, unless the caret is above them.
        top = max(0, len(lines) - height)
        if 0 <= caret_line < top:
            top = caret_line
        visible = [line.text for line in lines[top : top + height]]
        visible += [""] * (height - len(visible))
        rule = "─" * SETTINGS_FIELD_WIDTH
        arrow = ">" if focused else " "
        hint = theme.dialog_hint
        rows = [f"{arrow} {label}", f"[{hint}]    ┌{rule}┐[/{hint}]"]
        for index, line in enumerate(visible):
            on_caret_line = index + top == caret_line
            body = (
                _caret_markup(line, column=caret_column, style=theme.text_caret)
                if on_caret_line
                else _escape_markup(line)
            )
            # The caret takes a cell of its own past the end of its line.
            filled = max(len(line), caret_column + 1) if on_caret_line else len(line)
            rows.append(f"[{hint}]    │[/{hint}] {body}{' ' * (width - filled)}[{hint}]│[/{hint}]")
        rows.append(f"[{hint}]    └{rule}┘[/{hint}]")
        return rows

    def _checkbox_row(self, row: int, checked: bool, label: str) -> str:
        """One checkbox row: cursor arrow, `[x]` / `[ ]`, and its label."""
        theme = _dialog_theme(self)
        mark = f"[{theme.checkbox_mark}]\\[x][/{theme.checkbox_mark}]" if checked else "\\[ ]"
        arrow = ">" if self._cursor == row else " "
        return f"{arrow} {mark} {label}"

    def _radio_row(self, row: int, label: str) -> str:
        """One row of the editor radio group: cursor arrow, `(•)` / `( )`, and
        its label."""
        theme = _dialog_theme(self)
        selected = self._editor == SETTINGS_EDITOR_ROWS[row]
        mark = f"[{theme.checkbox_mark}](•)[/{theme.checkbox_mark}]" if selected else "( )"
        arrow = ">" if self._cursor == row else " "
        return f"{arrow} {mark} {label}"

    def _redraw(self) -> None:
        theme = _dialog_theme(self)
        lines: list[str] = ["[b]Settings[/b]", ""]
        lines.append(self._text_row(SETTINGS_ROW_BRANCH, "Default branch: "))
        lines.append("")
        lines.append(
            self._checkbox_row(
                SETTINGS_ROW_PREFIX,
                self._branch_prefix,
                "Use branch name as prefix in commit messages",
            )
        )
        lines.append("")
        lines.append(self._section_header("Commit message editor"))
        lines.append("")
        lines.append(self._radio_row(SETTINGS_ROW_EDITOR_BUILTIN, "Built-in editor"))
        environment = os.environ.get("EDITOR", "").strip()
        lines.append(
            self._radio_row(
                SETTINGS_ROW_EDITOR_ENVIRONMENT,
                f"$EDITOR ({_escape_markup(environment)})" if environment else "$EDITOR (not set)",
            )
        )
        lines.append(self._radio_row(SETTINGS_ROW_EDITOR_COMMAND, "Other editor:"))
        lines.append(self._text_row(SETTINGS_ROW_EDITOR_COMMAND_LINE, "      Command: "))
        lines.append(
            f"[{theme.dialog_hint}]"
            "    (an external editor opens the message in a temporary file)"
            f"[/{theme.dialog_hint}]"
        )
        lines.append("")
        lines.append(self._section_header("Experimental"))
        lines.append("")
        lines.append("  Tool for drafting commit messages:")
        lines.append(self._text_row(SETTINGS_ROW_COMMAND, "  Command: "))
        lines.extend(self._field_rows(SETTINGS_ROW_PROMPT, "  Prompt:"))
        lines.append(
            f"[{theme.dialog_hint}]"
            '    (run as: command "prompt + the files being committed")'
            f"[/{theme.dialog_hint}]"
        )
        lines.append("")
        lines.append(
            self._checkbox_row(
                SETTINGS_ROW_PARSE,
                self._parse_suggestions,
                "Parse suggestions from numbered list",
            )
        )
        lines.append("")
        lines.append(f"[{theme.dialog_hint}]{self._key_hint()}[/{theme.dialog_hint}]")
        try:
            self.query_one("#settings-content", Static).update("\n".join(lines))
        except WIDGET_LOOKUP_ERRORS:
            # Keys can arrive before compose() has run under test stubs; the
            # values are already recorded, so there is simply nothing to paint.
            pass

    def _key_hint(self) -> str:
        """The key line under the dialog, which is not the same in a framed
        field: the arrows belong to the caret there, and Tab is what leaves."""
        if self._cursor in self.FIELD_ROWS:
            return "(←→↑↓ move the caret, Tab leaves, Enter save, Esc cancel)"
        return "(↑↓/Tab move, Space toggle, Enter save, Esc cancel)"

    def move_cursor(self, delta: int) -> None:
        self._cursor = (self._cursor + delta) % SETTINGS_ROW_COUNT
        # The row is entered with its caret at the end, the same place the
        # dialog started with and the only one that needs no arrow keys.
        self._caret = len(self._row_value())
        self._redraw()

    def toggle_current(self) -> None:
        if self._cursor == SETTINGS_ROW_PREFIX:
            self._branch_prefix = not self._branch_prefix
        elif self._cursor == SETTINGS_ROW_PARSE:
            self._parse_suggestions = not self._parse_suggestions
        elif self._cursor in SETTINGS_EDITOR_ROWS:
            self._editor = SETTINGS_EDITOR_ROWS[self._cursor]
        self._redraw()

    def get_values(self) -> SettingsValues:
        return SettingsValues(
            branch_prefix=self._branch_prefix,
            draft_command=self._draft_command,
            draft_prompt=self._draft_prompt,
            default_branch=self._default_branch,
            parse_suggestions=self._parse_suggestions,
            editor=self._editor,
            editor_command=self._editor_command,
        )


class DraftResult(NamedTuple):
    """What the drafting tool produced. `ok` says whether `text` is a commit
    message or the reason there isn't one."""

    ok: bool
    text: str


# A line that opens a numbered suggestion: "1. feat: x", " 2) feat: x",
# "3: feat: x". The number is dropped; group 1 is the message it introduces.
NUMBERED_SUGGESTION_PATTERN = re.compile(r"^\s{0,3}\d{1,2}[.):]\s+(\S.*)$")

# The Markdown a drafting tool wraps its suggestions in: bold markers and
# code spans, removed from the text, and the fence around a code block, whose
# line is dropped whole. `_` is deliberately not here — it belongs to names
# like `__init__` or `test_app.py` far more often than it marks emphasis.
MARKDOWN_DELIMITER_PATTERN = re.compile(r"\*\*|`+")
CODE_FENCE_PATTERN = re.compile(r"^\s*(?:```+|~~~+)\s*\S*\s*$")


def parse_numbered_suggestions(text: str) -> list[str]:
    """The numbered items in `text`, without their numbers.

    A drafting tool asked for several candidate messages answers with a
    numbered list, usually wrapped in a sentence of its own before and after.
    Anything ahead of the first number is dropped; an item then keeps the
    blank and *indented* lines under it, which is how a suggestion with a
    body survives, and ends at the first line back in column 0 that isn't
    another number. That last part is what keeps the tool's closing remarks —
    "My pick: #2, because…" — out of the message the user picked: they are
    prose about the list, not part of the item they happen to follow.

    Only the item is ended, not the parse, so a tool that comments between
    its suggestions still yields all of them. The cost is a body written
    without indentation, which reads as the end of its item; the pick is
    editable before F2 either way, which is the remedy for that and for a
    tool that numbers something other than a message.
    """
    suggestions: list[list[str]] = []
    continuing = False
    for line in text.splitlines():
        match = NUMBERED_SUGGESTION_PATTERN.match(line)
        if match is not None:
            suggestions.append([match.group(1).strip()])
            continuing = True
        elif not continuing:
            continue
        elif line.strip() and not line.startswith((" ", "\t")):
            continuing = False
        else:
            suggestions[-1].append(line)
    return [joined for item in suggestions if (joined := _joined_suggestion(item))]


def _strip_markdown_delimiters(lines: list[str]) -> list[str]:
    """The item's lines with the markup a tool decorated them with taken off.

    A drafting tool writing a list writes it as Markdown — `**bold**` around
    the subject, backticks around the message or a filename in it, a fenced
    block around the whole thing — and a commit message is plain text, so the
    markers come off before the suggestion reaches the message box. A fence
    line goes entirely, because stripping its backticks would leave its
    language tag behind as a line of the message. The rest are removed marker
    by marker rather than in matched pairs: an item cut off at the first
    unindented line can end mid-emphasis, and a stray `**` in the message is
    exactly what this is here to prevent.
    """
    return [
        MARKDOWN_DELIMITER_PATTERN.sub("", line)
        for line in lines
        if CODE_FENCE_PATTERN.match(line) is None
    ]


def _joined_suggestion(lines: list[str]) -> str:
    """One parsed item as a commit message: the subject, then its body with
    the list indentation taken back off — that indent is what marked the
    lines as belonging to the item, not something the message asked for."""
    stripped = _strip_markdown_delimiters(lines)
    if not stripped:
        return ""
    subject, *body = stripped
    if not body:
        return subject.strip()
    dedented = textwrap.dedent("\n".join(body))
    return f"{subject}\n{dedented}".strip()


def _commit_message_subject(message: str) -> str:
    """The message's first line, marked as cut when there is more below it.

    The confirmation popup renders one command per row, so the `-m` argument
    shown there has to be a single line.
    """
    lines = message.strip().split("\n")
    if len(lines) == 1:
        return lines[0]
    return f"{lines[0]}{TRUNCATION_MARKER}"


class EditorResult(NamedTuple):
    """What an external editor left behind.

    `started` is False when the editor couldn't be run at all, and `detail`
    says why. Otherwise `message` is the edited message — or None when the
    editor exited with a failure status, which is how vim's `:cq` and its
    kind say "abandon this", and `detail` then carries that status.
    """

    started: bool
    message: str | None
    detail: str = ""


def commit_editor_template(message: str, filenames: list[str]) -> str:
    """The temporary file handed to the editor: the message so far, then
    git's scissors line and, under it, the help text and the files going into
    the commit — which is what the built-in dialog can't show and the editor
    has room for."""
    help_lines = [
        COMMIT_EDITOR_SCISSORS,
        "# Do not modify or remove the line above.",
        "# Everything below it is ignored. An empty message cancels the commit.",
        "#",
        "# Files in this commit:",
        *(f"#\t{filename}" for filename in filenames),
    ]
    return "\n".join([message, "", *help_lines, ""])


def strip_commit_editor_text(text: str) -> str:
    """The message in an edited `commit_editor_template()`: everything above
    the scissors line, with trailing whitespace and the blank lines around it
    taken off. A file whose scissors line was deleted is kept whole, as git
    keeps it."""
    lines = text.splitlines()
    if COMMIT_EDITOR_SCISSORS in lines:
        lines = lines[: lines.index(COMMIT_EDITOR_SCISSORS)]
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def run_commit_editor(
    *, argv: list[str], message: str, filenames: list[str], cwd: str
) -> EditorResult:
    """Edit `message` in the editor `argv` names and return what it saved.

    The message goes to a temporary `COMMIT_EDITMSG` and the editor is run
    as `<argv> <path>`, on the terminal as it is — the caller has suspended
    the app, so the editor owns the screen and the keyboard until it exits.
    The directory the file sits in is removed again whatever happens.

    Ctrl+C inside an editor that doesn't claim it reaches this process too;
    it is read as the editor being abandoned rather than let out, because an
    exception escaping here would skip `App.suspend()`'s resume.
    """
    with tempfile.TemporaryDirectory(prefix="gitnc-") as directory:
        path = Path(directory) / COMMIT_EDITOR_FILENAME
        path.write_text(commit_editor_template(message, filenames), encoding="utf-8")
        try:
            completed = subprocess.run([*argv, str(path)], cwd=cwd, check=False)
        except OSError as exc:
            return EditorResult(
                started=False, message=None, detail=f"Could not run {argv[0]}: {exc}"
            )
        except KeyboardInterrupt:
            return EditorResult(started=True, message=None, detail=f"{argv[0]} was interrupted")
        if completed.returncode != 0:
            return EditorResult(
                started=True,
                message=None,
                detail=f"{argv[0]} exited with status {completed.returncode}",
            )
        try:
            edited = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return EditorResult(
                started=True, message=None, detail=f"Could not read the message back: {exc}"
            )
    return EditorResult(started=True, message=strip_commit_editor_text(edited))


def commit_draft_prompt(template: str, filenames: list[str]) -> str:
    """The prompt handed to the drafting tool: the template from the
    settings, then the files going into the commit, one per line."""
    return "\n".join([template.rstrip(), *filenames])


def _pump_draft_output(
    *,
    stream: IO[str] | None,
    sink: list[str],
    on_output: Callable[[str], None] | None,
) -> None:
    """Read `stream` a line at a time into `sink`, reporting each line.

    Line at a time rather than `.read()` is the whole point: the caller shows
    the tool's progress while it is still running. The SGR strip matches the
    one `GIT` does — the lines are rendered literally.
    """
    if stream is None:
        return
    with stream:
        for raw in stream:
            line = ANSI_SGR_PATTERN.sub("", raw).rstrip("\r\n")
            sink.append(line)
            if on_output is not None:
                on_output(line)


def run_commit_draft(
    *,
    argv: list[str],
    prompt: str,
    cwd: str,
    on_output: Callable[[str], None] | None = None,
) -> DraftResult:
    """Run the drafting tool and return its output as a commit message.

    Called from a thread worker (see `GitNightCommanderApp._commit_draft_worker`), so it
    touches no widget and no app state; `on_output` is how the caller gets
    each line of stdout and stderr as it is produced, so a tool that takes
    minutes can show what it is doing rather than only that it is busy. That
    is why this is `Popen` and two pumps instead of `subprocess.run`: the
    latter hands its output over only once the process has exited.

    stdout is the commit message and stderr is the failure detail, so the two
    are kept apart even though both are reported as progress. stderr gets its
    own reader thread — reading them in sequence would deadlock as soon as
    one filled its pipe buffer while the other was being drained.

    The tool's stdin is closed: the run shows on the previous screen, but it
    is not an interactive session — a tool that decides to prompt would sit
    there waiting for a terminal nobody is typing into.
    """
    try:
        process = subprocess.Popen(
            [*argv, prompt],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return DraftResult(ok=False, text=f"Could not run {argv[0]}: {exc}")

    out_lines: list[str] = []
    err_lines: list[str] = []
    # `subprocess.run(timeout=...)` used to enforce this; with the pumps
    # blocking on the pipes instead, a watchdog kills the process and the
    # pumps end at EOF.
    timed_out = threading.Event()

    def give_up() -> None:
        timed_out.set()
        process.kill()

    watchdog = threading.Timer(COMMIT_DRAFT_TIMEOUT_SECONDS, give_up)
    watchdog.daemon = True
    errors = threading.Thread(
        target=_pump_draft_output,
        kwargs={"stream": process.stderr, "sink": err_lines, "on_output": on_output},
        daemon=True,
    )
    watchdog.start()
    errors.start()
    interrupted = False
    try:
        _pump_draft_output(stream=process.stdout, sink=out_lines, on_output=on_output)
        process.wait()
    except KeyboardInterrupt:
        # Ctrl+C while the run is on the previous screen: the app is
        # suspended, so the terminal is back in cooked mode and the interrupt
        # arrives here rather than in the TUI. It reaches the tool too (same
        # process group), so the kill is only for a tool that ignored it.
        # Letting it escape would skip `App.suspend()`'s resume and leave the
        # terminal outside the alternate screen.
        interrupted = True
        process.kill()
        process.wait()
    finally:
        watchdog.cancel()
        errors.join(timeout=COMMIT_DRAFT_JOIN_SECONDS)

    if interrupted:
        return DraftResult(ok=False, text=f"{argv[0]} cancelled")
    if timed_out.is_set():
        return DraftResult(
            ok=False, text=f"{argv[0]} timed out after {COMMIT_DRAFT_TIMEOUT_SECONDS}s"
        )
    if process.returncode != 0:
        detail = [line for line in err_lines if line.strip()]
        suffix = f": {detail[-1]}" if detail else ""
        return DraftResult(ok=False, text=f"{argv[0]} failed{suffix}")
    message = "\n".join(out_lines).strip()
    if not message:
        return DraftResult(ok=False, text=f"{argv[0]} produced no commit message")
    return DraftResult(ok=True, text=message)


class CommitTextArea(TextArea):
    """TextArea that surrenders F2 / F4 / Esc to the commit dialog flow.

    Why: TextArea must own most keys so the user can type a multi-line
    message. We only peel off the keys that submit, draft or cancel, and
    delegate those back to the owning dialog.

    F2 is the Norton Commander / MC "save" key, matching the F9/F10 bindings
    this app already uses, and function keys survive terminal flow control
    and multiplexers intact.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("f2", "commit_submit", "Commit", show=False),
        Binding("f4", "commit_draft", "Draft", show=False),
        Binding("escape", "commit_cancel", "Cancel", show=False),
    ]

    def _dialog_action(self, name: str) -> None:
        """Forward to the owning CommitDialog screen.

        Resolved by name rather than isinstance so this keeps working under
        the test stubs, where the screen is a mock.
        """
        handler = getattr(self.screen, name, None)
        if callable(handler):
            handler()

    def action_commit_submit(self) -> None:
        self._dialog_action("submit")

    def action_commit_draft(self) -> None:
        self._dialog_action("draft")

    def action_commit_cancel(self) -> None:
        self._dialog_action("cancel")


class CommitDialog(ModalScreen["str | None"]):
    """Modal dialog that captures a multi-line commit message.

    Dismisses with the message on F2, or None on Esc. F4 — the Draft button —
    asks the app to run the configured drafting tool and drops its output
    into the text area, where it stays as editable as anything typed by hand.
    That run happens on the previous screen, which is where everything the
    tool prints is shown; the log pane under the buttons is for the terminal
    that can't be suspended, where it is the only way to tell a tool still
    working from one that has hung.

    The box fills the screen, both ways: a commit message is prose the user
    may want to see whole, so the dialog is the largest thing the app puts
    on screen rather than a popup measured against its content. The text
    area takes every row the title, buttons, log pane and hint leave over,
    and scrolls once the message runs past them.

    Unlike the other dialogs this one carries BINDINGS as well as
    CommitTextArea's copy of them. It has no `on_key` stopping events, so the
    screen's bindings are reached normally — which is what makes F2/F4/Esc
    work while the Draft button, the other focusable widget here, has focus.
    """

    AUTO_FOCUS = "#commit-message"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("f2", "commit_submit", "Commit", show=False),
        Binding("f4", "commit_draft", "Draft", show=False),
        Binding("escape", "commit_cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = f"""
    CommitDialog {{
        align: center middle;
    }}
    CommitDialog #commit-body {{
        background: $panel;
        border: solid $accent;
        width: 100%;
        height: 100%;
        padding: 1 2;
    }}
    CommitDialog Label {{
        width: 100%;
        height: auto;
    }}
    CommitDialog #commit-message {{
        width: 100%;
        /* The rows nothing else needs; a longer message scrolls inside. */
        height: 1fr;
        min-height: 3;
        border: solid $accent;
    }}
    CommitDialog #commit-buttons {{
        width: 100%;
        height: auto;
        align-horizontal: left;
    }}
    CommitDialog #commit-draft {{
        margin: 0 2 0 0;
    }}
    CommitDialog #commit-status {{
        /* Buttons are three rows tall; centre the note against the label
           inside the one next to it. */
        height: 3;
        content-align-vertical: middle;
    }}
    CommitDialog #commit-output {{
        width: 100%;
        height: {COMMIT_DRAFT_OUTPUT_ROWS};
        border: solid $accent;
        background: transparent;
        /* Nothing to show until the Draft button runs something. */
        display: none;
    }}
    CommitDialog #commit-output-content {{
        width: auto;
        height: auto;
    }}
    """

    def __init__(self, prefill: str = "") -> None:
        super().__init__()
        self.prefill = prefill
        self.output_lines: list[str] = []
        self.drafting = False

    def compose(self) -> ComposeResult:
        theme = _dialog_theme(self)
        with Vertical(id="commit-body"):
            yield Label("[b]Commit message[/b]", id="commit-title")
            yield CommitTextArea(self.prefill, id="commit-message")
            with Horizontal(id="commit-buttons"):
                yield Button("Draft (F4)", id="commit-draft")
                yield Label("", id="commit-status")
            with ScrollableContainer(id="commit-output"):
                yield Static("", id="commit-output-content")
            yield Label(
                f"[{theme.dialog_hint}](F2 commit, F4 draft, Esc cancel)[/{theme.dialog_hint}]",
                id="commit-hint",
            )

    def on_mount(self) -> None:
        """Park the cursor at the end of the prefill — after the branch
        prefix, or after the last line of a message reopened from the commit
        confirmation — so the user types after it rather than before it, and
        a message taller than the text area is scrolled to where the cursor
        is."""
        lines = self.prefill.split("\n")
        self.move_cursor_to(row=len(lines) - 1, column=len(lines[-1]))

    def move_cursor_to(self, *, row: int, column: int) -> None:
        """Put the text cursor at `row`/`column`, if there is a text area to
        put it in — keys and worker results both arrive before compose() has
        run under the test stubs."""
        try:
            text_area = self.query_one("#commit-message", TextArea)
        except WIDGET_LOOKUP_ERRORS:
            return
        move_cursor = getattr(text_area, "move_cursor", None)
        if callable(move_cursor):
            try:
                move_cursor((row, column))
            except (TypeError, ValueError):
                pass

    def get_text(self) -> str:
        try:
            return self.query_one("#commit-message", TextArea).text
        except WIDGET_LOOKUP_ERRORS:
            return ""

    def set_text(self, message: str) -> None:
        """Replace the message with `message` and hand the user back the
        text area, so a drafted message can be edited straight away — the
        Draft button holds focus at the point this arrives."""
        try:
            text_area = self.query_one("#commit-message", TextArea)
        except WIDGET_LOOKUP_ERRORS:
            return
        load_text = getattr(text_area, "load_text", None)
        if callable(load_text):
            load_text(message)
        lines = message.split("\n")
        self.move_cursor_to(row=len(lines) - 1, column=len(lines[-1]))
        focus = getattr(text_area, "focus", None)
        if callable(focus):
            focus()

    def set_drafting(self, drafting: bool) -> None:
        """Show or clear the "working" note, and lock the Draft button while
        the tool runs so a slow one can't be started twice.

        Starting a run empties the log, which is also what clears a previous
        run's output off the dialog; a run that put lines there leaves them on
        screen when it finishes, because what the tool said about a message it
        couldn't write is exactly what the user needs to read.
        """
        if drafting:
            self.output_lines = []
        self.drafting = drafting
        theme = _dialog_theme(self)
        self._render_output()
        try:
            status = self.query_one("#commit-status", Label)
            button = self.query_one("#commit-draft", Button)
        except WIDGET_LOOKUP_ERRORS:
            return
        note = f"[{theme.dialog_hint}]Drafting commit message…[/{theme.dialog_hint}]"
        status.update(note if drafting else "")
        button.disabled = drafting

    def append_output(self, line: str) -> None:
        """Add one line of the drafting tool's output to the log.

        Called once per line the tool prints, from the UI thread — the worker
        hands the lines over through `call_from_thread`. Only the worker: a
        run on the previous screen has already shown the user every line, and
        printing them here as well would leave the message the user came for
        buried under a repeat of the run.
        """
        self.output_lines.append(line)
        # Drop the oldest lines rather than the newest: the tail is the part
        # that says what the tool is doing now.
        del self.output_lines[:-COMMIT_DRAFT_OUTPUT_LINES]
        self._render_output()

    def _render_output(self) -> None:
        """Redraw the log pane, hidden until there is a run to show.

        The pane is pinned to its last line so the newest output is the
        visible one without the user scrolling.
        """
        try:
            container = self.query_one("#commit-output", ScrollableContainer)
            content = self.query_one("#commit-output-content", Static)
        except WIDGET_LOOKUP_ERRORS:
            return
        content.update("\n".join(self.output_lines))
        container.display = self.drafting or bool(self.output_lines)
        container.scroll_end(animate=False)

    def draft(self) -> None:
        """F4 / Draft: hand the request to the app, which owns the settings
        and the worker that keeps the tool off the UI thread.

        Resolved by name rather than isinstance so this keeps working under
        the test stubs, where the app is a mock.
        """
        try:
            app = self.app
        except NO_SCREEN_ERRORS:
            return
        request = getattr(app, "request_commit_draft", None)
        if callable(request):
            request(self)

    def on_button_pressed(self, event) -> None:
        event.stop()
        if getattr(event.button, "id", None) == "commit-draft":
            self.draft()

    def action_commit_submit(self) -> None:
        self.submit()

    def action_commit_draft(self) -> None:
        self.draft()

    def action_commit_cancel(self) -> None:
        self.cancel()

    def submit(self) -> None:
        """F2: hand the message back, refusing to dismiss on an empty one."""
        message = self.get_text().strip()
        if not message:
            self.app.notify("Commit message cannot be empty")
            return
        self.dismiss(message)

    def cancel(self) -> None:
        self.dismiss(None)


class SuggestionDialog(ModalScreen["str | None"]):
    """Modal list of the messages a drafting tool suggested.

    Opened over the commit dialog when "Parse suggestions from numbered list"
    is on and the tool answered with more than one. Dismisses with the picked
    message, which the commit dialog loads into its text area — a pick is a
    starting point, not a commitment, and stays as editable as anything typed
    by hand.

    Rows show each suggestion's first line: the list is for choosing between
    them, and a message with a body would push the rest off the screen.
    """

    AUTO_FOCUS = "#suggestion-list"

    DEFAULT_CSS = f"""
    SuggestionDialog {{
        align: center middle;
    }}
    SuggestionDialog #suggestion-body {{
        background: $panel;
        border: solid $accent;
        width: 100%;
        height: auto;
        max-height: 100%;
        padding: 1 2;
    }}
    SuggestionDialog Label {{
        width: 100%;
        height: auto;
    }}
    SuggestionDialog #suggestion-list {{
        width: 100%;
        height: auto;
        max-height: {SUGGESTION_DIALOG_MAX_ROWS};
        border: none;
        background: transparent;
        padding: 0;
    }}
    SuggestionDialog #suggestion-list:focus {{
        border: none;
        outline: none;
    }}
    """

    def __init__(self, suggestions: list[str]) -> None:
        super().__init__()
        self.suggestions = list(suggestions)

    def compose(self) -> ComposeResult:
        theme = _dialog_theme(self)
        with Vertical(id="suggestion-body"):
            yield Label("[b]Pick a commit message[/b]", id="suggestion-title")
            yield OptionList(
                *[Option(label) for label in self.option_labels()],
                id="suggestion-list",
            )
            yield Label(
                f"[{theme.dialog_hint}]"
                "(↑↓ move, 1-9 or Enter picks, Esc cancels)"
                f"[/{theme.dialog_hint}]",
                id="suggestion-hint",
            )

    def option_labels(self) -> list[str]:
        """The rows as rendered: numbered as the tool numbered them, each cut
        to its first line. Escaped, because a message is the user's text and
        `[b]` in it is not markup."""
        return [
            f"{index}. {_escape_markup(_commit_message_subject(suggestion))}"
            for index, suggestion in enumerate(self.suggestions, start=1)
        ]

    def pick(self, index: int) -> None:
        """Dismiss with suggestion `index` (0-based), ignoring one that isn't
        there — the digit keys can name a row past the end of a short list."""
        if 0 <= index < len(self.suggestions):
            self.dismiss(self.suggestions[index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.pick(event.option_index)

    def on_key(self, event) -> None:
        """Esc cancels and a digit picks that row; arrows and Enter are left
        to the OptionList, which is what moves and selects."""
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.dismiss(None)
            return
        character = getattr(event, "character", None)
        if isinstance(character, str) and character.isdigit() and event.key == character:
            event.stop()
            event.prevent_default()
            self.pick(int(character) - 1)


DIFF_HUNK_PATTERN = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Lines git repeats around every file in a patch. FileDiff drops them; the
# commit view keeps them, since there they say which file follows.
DIFF_FILE_HEADER_PREFIXES = ("diff ", "index ", "--- ", "+++ ")

# `commit <sha>` / `Author:` / `Date:` / … block that opens `git show` output.
COMMIT_HEADER_PATTERN = re.compile(
    r"^(commit [0-9a-f]{7,}|Merge:|Author:|AuthorDate:|Commit:|CommitDate:|Date:)"
)

# A `git show --stat` row: " path/to/file | 18 +++++++---------". Group 1 is
# everything up to the graph, group 2 the run of +/- characters.
DIFFSTAT_PATTERN = re.compile(r"^(\s+\S.*\|\s+\d+\s+)([+-]+)$")


def _diff_line_styles(line: str, *, theme: UITheme) -> tuple[str, str | None]:
    """Return ``(gutter style, line style)`` for one unified-diff body line.

    Shared by `FileDiff` and `render_commit_detail` so the two diff views
    color added/removed lines identically. The commit view has no
    line-number column and ignores the gutter style.
    """
    if line.startswith("+"):
        return theme.diff_added_line_number, theme.diff_added_line
    if line.startswith("-"):
        return theme.diff_removed_line_number, theme.diff_removed_line
    return theme.diff_context_line_number, None


def render_commit_detail(detail_text: str, *, theme: UITheme) -> Text:
    """Render `git show` output for a commit into styled `Text`.

    The header block and commit message keep git's own layout, the diffstat
    graph and any patch body get the same +/- colors `FileDiff` uses, and
    hunk markers are kept (unlike in `FileDiff`, where the line-number
    gutter already carries that information). No gutter is drawn here
    because the text spans several files rather than one.
    """
    text = Text()
    for index, line in enumerate(detail_text.splitlines()):
        if index:
            text.append("\n")
        if COMMIT_HEADER_PATTERN.match(line) or line.startswith(DIFF_FILE_HEADER_PREFIXES):
            text.append(line, style=theme.commit_header_line)
            continue
        stat = DIFFSTAT_PATTERN.match(line)
        if stat:
            text.append(stat.group(1))
            for char in stat.group(2):
                added = char == "+"
                text.append(
                    char,
                    style=theme.diff_added_line if added else theme.diff_removed_line,
                )
            continue
        if DIFF_HUNK_PATTERN.match(line):
            text.append(line, style=theme.diff_hunk_header)
            continue
        _, line_style = _diff_line_styles(line, theme=theme)
        text.append(line, style=line_style)
    return text


class CommitDetail(Static):
    """Shows the full diff for the selected commit."""

    DEFAULT_CSS = """
    CommitDetail {
        border: solid $accent;
        padding: 1 2;
        height: 1fr;
        overflow-y: auto;
    }
    """

    def show(self, detail_text: str) -> None:
        theme = self.app._active_ui_theme()  # pyright: ignore[reportAttributeAccessIssue]
        self.update(render_commit_detail(detail_text, theme=theme))


class FileDiff(ScrollableContainer):
    """Shows the diff for a selected status entry."""

    can_focus = True

    DEFAULT_CSS = """
    FileDiff {
        border: solid $accent;
        height: 1fr;
        display: none;
    }
    FileDiff:focus {
        border: solid $success;
    }
    FileDiff Static {
        width: 100%;
        height: auto;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="diff-content")

    def on_key(self, event) -> None:
        if event.key == "up":
            self.scroll_up(animate=False)
            event.stop()
        elif event.key == "down":
            self.scroll_down(animate=False)
            event.stop()

    def show(self, diff_text: str, filename: str = "") -> None:
        self.display = True
        self.border_title = filename
        self.scroll_home(animate=False)
        theme = self.app._active_ui_theme()  # pyright: ignore[reportAttributeAccessIssue]
        text = Text()
        old_line = 0
        new_line = 0
        first = True

        def nl():
            nonlocal first
            if not first:
                text.append("\n")
            first = False

        for line in diff_text.splitlines():
            hunk = DIFF_HUNK_PATTERN.match(line)
            if hunk:
                old_line = int(hunk.group(1))
                new_line = int(hunk.group(2))
                continue

            if line.startswith(DIFF_FILE_HEADER_PREFIXES):
                continue

            nl()
            gutter_style, line_style = _diff_line_styles(line, theme=theme)
            if line.startswith("+"):
                number = new_line
                new_line += 1
            elif line.startswith("-"):
                number = old_line
                old_line += 1
            else:
                number = new_line
                old_line += 1
                new_line += 1
            text.append(f" {number:>4}  ", style=gutter_style)
            text.append(line, style=line_style)

        self.query_one("#diff-content", Static).update(text)
        self.focus()

    def show_content(self, content: str, filename: str = "") -> None:
        """Render plain file text with a line-number gutter, no diff parsing.

        Used for untracked files where there is no diff to display.
        """
        self.display = True
        self.border_title = filename
        self.scroll_home(animate=False)
        theme = self.app._active_ui_theme()  # pyright: ignore[reportAttributeAccessIssue]
        text = Text()
        for n, line in enumerate(content.splitlines(), 1):
            if n > 1:
                text.append("\n")
            text.append(f" {n:>4}  ", style=theme.diff_context_line_number)
            text.append(line)
        self.query_one("#diff-content", Static).update(text)
        self.focus()


class CommitList(ListView):
    """Scrollable list of git commits."""

    DEFAULT_CSS = """
    CommitList {
        width: 1fr;
        border: solid $accent;
        height: 1fr;
    }
    ListItem {
        padding: 0 1;
    }
    ListItem:hover {
        background: $boost;
    }
    ListItem.-highlight {
        background: $accent 30%;
    }
    """


class StatusListItem(ListItem):
    """ListItem that only forwards double-clicks. Single clicks highlight only.

    Textual's ListItem._on_click posts _ChildClicked on every click regardless
    of chain length, so single-clicks end up firing ListView.Selected. We want
    file-manager semantics: single click = highlight, double click = open.

    Why: Textual dispatches `_on_click` to every class in the MRO
    (textual/message_pump.py:758 — it walks `self.__class__.__mro__` and
    yields each class's own `_on_click`). So plain `event.stop()` here is NOT
    enough — `ListItem._on_click` would still run and post `_ChildClicked`.
    `event.prevent_default()` sets `_no_default_action`, which breaks the MRO
    loop (message_pump.py:759) and skips the base-class handler.

    Keyboard Enter is unaffected because it bypasses `_on_click` entirely
    (ListView.action_select_cursor posts Selected directly).
    """

    def _on_click(self, event) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        # CTRL+click toggles multi-selection. SHIFT+click is reserved by most
        # terminals for native text-selection, so we use CTRL which is
        # forwarded reliably. Guard with `is True` so MagicMock attributes in
        # tests (truthy by default) don't accidentally take the ctrl branch.
        if getattr(event, "ctrl", False) is True:
            event.prevent_default()
            event.stop()
            list_view = self.parent
            if list_view is None:
                return
            try:
                index = list_view.children.index(self)  # pyright: ignore[reportAttributeAccessIssue]
            except (AttributeError, ValueError):
                return
            app = self.app
            toggle = getattr(app, "_toggle_status_selection", None)
            if callable(toggle):
                toggle(index)
            return
        if getattr(event, "chain", 1) >= 2:
            return
        event.prevent_default()
        event.stop()
        # Replicate the highlight half of ListView._on_list_item__child_clicked
        # (focus + move cursor) without the Selected message that opens the
        # file. Arrow keys then continue from this row.
        list_view = self.parent
        if list_view is None:
            return
        list_view.focus()  # pyright: ignore[reportAttributeAccessIssue]
        try:
            list_view.index = list_view.children.index(self)  # pyright: ignore[reportAttributeAccessIssue]
        except (AttributeError, ValueError):
            pass


class StatusList(ListView):
    """Scrollable list of git status entries."""

    DEFAULT_CSS = """
    StatusList {
        border: solid $accent;
        height: 1fr;
    }
    StatusList ListItem {
        padding: 0 1;
    }
    StatusList ListItem:hover {
        background: $boost;
    }
    StatusList ListItem.-highlight {
        background: $cursor-row-background;
        color: $cursor-row-foreground;
    }
    StatusList ListItem.selected {
        background: $selected-file-background;
        color: $selected-file-foreground;
        text-style: bold;
    }
    StatusList ListItem.selected.-highlight {
        background: $selected-cursor-row-background;
        color: $selected-cursor-row-foreground;
        text-style: bold;
    }
    """

    def on_resize(self, event) -> None:
        """Re-flow rows so the right-aligned columns stay flush to the right
        of the list when the terminal is resized."""
        refresh = getattr(self.app, "_refresh_status_layout", None)
        if callable(refresh):
            refresh()

    def on_focus(self, event) -> None:
        """Re-apply the highlight class to the current row when the list is
        focused again.

        Why: the row keeps its index while focus is elsewhere (the inline
        diff, a dialog), but the ``-highlight`` class can have been dropped by
        a rebuild in the meantime, and Textual only re-runs ``watch_index``
        when the value changes.
        """
        index = self.index
        if index is not None:
            self.watch_index(index, index)

    def on_key(self, event) -> None:
        if event.key in ("shift+up", "shift+down"):
            extend = getattr(self.app, "_extend_status_selection", None)
            if callable(extend):
                extend(-1 if event.key == "shift+up" else 1)
            event.stop()
            event.prevent_default()
        elif event.key == "space":
            toggle = getattr(self.app, "_toggle_current_status_selection", None)
            if callable(toggle):
                toggle()
            event.stop()
            event.prevent_default()


class GitNightCommanderApp(App):
    """A simple TUI git log browser."""

    TITLE = "GitNightCommander"
    SUB_TITLE = "git log browser"

    # Disable Textual's command palette entirely. This also hides the
    # built-in Screenshot system command, which is only reachable through
    # the palette.
    ENABLE_COMMAND_PALETTE = False

    # Textual's default AUTO_FOCUS is "*", which focuses whichever widget
    # happens to answer `focusable` first — including hidden overlays such as
    # the settings dialog, whose readiness is timing-dependent. Name the file
    # list explicitly so startup focus is deterministic.
    AUTO_FOCUS = "#status_list"

    # Ordered list of menu IDs — drives F9 open and left/right navigation.
    MENU_ORDER: ClassVar[list[str]] = [menu_id for _, menu_id in MENU_BAR]

    # Aliases are bound with show=False: the footer keys off the binding, not
    # the action, so a shown alias would list its action's description twice.
    BINDINGS: ClassVar[list[BindingType]] = [
        *(
            Binding(
                key,
                action,
                description,
                show=show,
                key_display=_shortcut_key_display(key),
                priority=(action == "quit"),
            )
            for key, action, description, show in SHORTCUTS
        ),
        *(
            Binding(key, action, SHORTCUT_DESCRIPTIONS_BY_ACTION.get(action, action), show=False)
            for key, action in SHORTCUT_ALIASES
        ),
    ]

    CSS = """
    Screen {
        layout: horizontal;
        layers: default overlay;
        background: $background;
        color: $foreground;
    }
    Header {
        background: $panel;
        color: $foreground;
    }
    ContentSwitcher {
        width: 100%;
        height: 1fr;
    }
    #history-view {
        width: 100%;
        height: 1fr;
    }
    #history-left {
        width: 50%;
    }
    #history-right {
        width: 50%;
    }
    #status-view {
        width: 100%;
        height: 1fr;
        layout: vertical;
    }
    #status-body {
        width: 100%;
        height: 1fr;
    }
    #status_list {
        width: 40%;
        min-width: 20;
    }
    #file-diff {
        width: 60%;
    }
    #status-view.long-mode #status_list {
        width: 100%;
    }
    #status-view.long-mode #file-diff {
        display: none;
    }
    #column-header {
        height: 1;
        width: 100%;
        padding: 0 2;
        color: $text-muted;
        background: $panel;
    }
    #submodule-warnings {
        height: auto;
        width: 100%;
        padding: 0 2;
        background: $panel;
    }
    #submodule-warnings.empty {
        display: none;
    }
    #diff-view {
        width: 100%;
        height: 1fr;
    }
    #diff-full {
        width: 100%;
        height: 1fr;
    }
    #meta {
        height: 3;
        padding: 0 2;
        border: solid $accent;
        color: $text-muted;
    }
    #status-header {
        height: 1;
        width: 100%;
        padding: 0 1;
        color: $text-muted;
        background: $panel;
    }
    """

    def __init__(self, repo_path: str = ".") -> None:
        super().__init__()
        self._register_app_themes()
        self.theme = MIDNIGHT_COMMANDER_THEME_NAME
        self.repo_path = repo_path
        self.git = GIT(repo_path)
        self._screen = Terminal()
        self.commits: list[Commit] = []
        self.status_filelist: GitFilelist = GitFilelist()
        self.file_list_mode: str = MODE_SHORT
        self.file_list_filter: str = FILTER_NONE
        self._last_status_entry: GitEntry | None = None
        self._pending_commit_externals: list[str] = []
        self._pending_commit_staged: list[GitEntry] = []
        self._pending_commit_targets: list[GitEntry] = []
        # Filled in by the status worker; _update_submodule_warnings renders
        # from this cache so a resize can re-flow the list without shelling
        # out to git again.
        self._submodule_mismatches: list[tuple[str, str | None, str | None]] = []
        # Newest issued serial per worker group; see _new_request.
        self._request_serials: dict[str, int] = {}
        # True while a pull or push worker is in flight. `exclusive=True`
        # wouldn't help here: it cancels a superseded worker's asyncio task,
        # but the thread keeps running, so a second P would reach the network
        # rather than replace the first push.
        self._remote_running: bool = False

    def _register_app_themes(self) -> None:
        for ui_theme in THEMES:
            self.register_theme(ui_theme.get_theme())

    def _active_ui_theme(self) -> UITheme:
        """Return the UITheme instance backing the currently active theme.

        Falls back to MIDNIGHT_COMMANDER_THEME when the active name does not
        match any registered theme (e.g. when self.theme is unset in tests).
        """
        name = getattr(self, "theme", None)
        return _UI_THEMES_BY_NAME.get(name or "", MIDNIGHT_COMMANDER_THEME)

    @property
    def status_entries(self) -> GitFilelist:
        return self.status_filelist

    @status_entries.setter
    def status_entries(self, entries: GitFilelist | list[GitEntry]) -> None:
        if isinstance(entries, GitFilelist):
            self.status_filelist = entries
            return
        self.status_filelist = GitFilelist(entries)

    def compose(self) -> ComposeResult:
        yield Header()
        yield MenuBar()
        with ContentSwitcher(initial="status-view"):
            with Vertical(id="status-view"):
                yield Label("", id="submodule-warnings", classes="empty")
                yield Label("", id="column-header")
                with Horizontal(id="status-body"):
                    yield StatusList(id="status_list")
                    yield FileDiff(id="file-diff")
                yield Label("", id="status-header")
            with Horizontal(id="history-view"):
                with Vertical(id="history-left"):
                    yield CommitList(id="commit_list")
                with Vertical(id="history-right"):
                    yield Label("", id="meta")
                    yield CommitDetail(id="detail")
            with Vertical(id="diff-view"):
                yield FileDiff(id="diff-full")
        yield DropdownMenu(self._file_menu_items(), id="dropdown_file")
        yield DropdownMenu(REPO_MENU, id="dropdown_repo")
        yield DropdownMenu(VIEW_MENU, id="dropdown_view")
        yield DropdownMenu(OPTIONS_MENU, id="dropdown_options")
        yield DropdownMenu(HELP_MENU, id="dropdown_help")
        for submenu in SUBMENUS:
            yield DropdownMenu(submenu.items, id=submenu.dropdown_id)
        yield Footer()

    def on_mount(self) -> None:
        self._load_saved_theme()
        self._offer_top_level_repository(then=self._start)

    def _start(self) -> None:
        self._load_status()
        self._load_commits()
        self._warn_if_started_from_midnight_commander()

    def _offer_top_level_repository(self, then: Callable[[], None]) -> None:
        """Ask to move to the outermost superproject when started in a submodule.

        Runs *then* once the question is answered (or at once, when there is
        nothing to ask), so the first `git status` reads the repository the
        user settled on rather than one it is about to leave. The chain is a
        `git rev-parse` per nesting level, which doesn't grow with the repo,
        so it runs inline.
        """
        chain = self.git.repository_chain()
        if len(chain) < 2:
            then()
            return
        rows = [f"submodule  {path}" for path in chain[:-1]]
        rows.append(f"top-level  {chain[-1]}")

        def confirmed() -> None:
            self._switch_repository(chain[-1])
            then()

        self._show_confirm(SUPERPROJECT_PROMPT, rows, on_confirm=confirmed, on_cancel=then)

    def _switch_repository(self, path: str) -> None:
        """Point the app at *path*; the caller reloads the views.

        The process moves there too, so the `Ctrl+O` shell and the tools run
        from the previous screen start where the file list is.
        """
        self.repo_path = path
        self.git = GIT(path)
        try:
            os.chdir(path)
        except OSError:
            pass

    def _warn_if_started_from_midnight_commander(self) -> None:
        if not started_from_midnight_commander():
            return

        def resolved(continue_: bool | None) -> None:
            if continue_:
                self._focus_active_view()
            else:
                self.action_quit()

        self.push_screen(
            MidnightCommanderDialog(message=MIDNIGHT_COMMANDER_WARNING),
            callback=resolved,
        )

    def _settings_path(self) -> Path:
        config_home = os.environ.get("XDG_CONFIG_HOME")
        config_root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
        return config_root / "gitnc" / SETTINGS_FILENAME

    def _load_settings(self) -> dict[str, object]:
        try:
            settings = json.loads(self._settings_path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def _save_settings(self, settings: dict[str, object]) -> bool:
        settings_path = self._settings_path()
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(settings, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            return False
        return True

    def _load_saved_theme(self) -> None:
        theme_name = self._load_settings().get("theme")
        if not isinstance(theme_name, str):
            return
        try:
            self.theme = theme_name
        except InvalidThemeError:
            return
        self._restyle_menu_mnemonics()

    @staticmethod
    def _menu_label(text: str, *, marker: str = MENU_MARKER_BLANK) -> str:
        """Prefix *text* with a one-cell marker gutter and its separating gap."""
        return f"{marker}{MENU_MARKER_GAP}{text}"

    def _file_menu_items(self) -> list[tuple[str, str]]:
        def radio(mode: str) -> str:
            return MENU_RADIO_ON if self.file_list_mode == mode else MENU_RADIO_OFF

        def filter_radio(file_filter: str) -> str:
            return MENU_RADIO_ON if self.file_list_filter == file_filter else MENU_RADIO_OFF

        return [
            (
                self._menu_label("&Short file list", marker=radio(MODE_SHORT)),
                "short_file_list",
            ),
            (
                self._menu_label("&Long file list", marker=radio(MODE_LONG)),
                "long_file_list",
            ),
            (
                self._menu_label("&All files", marker=filter_radio(FILTER_NONE)),
                "file_filter_none",
            ),
            (
                self._menu_label(
                    "Collapse &untracked folders", marker=filter_radio(FILTER_UNTRACKED_DIRS)
                ),
                "file_filter_untracked_dirs",
            ),
            (self._menu_label("&Refresh"), "refresh"),
            (self._menu_label("&Delete"), "delete_file"),
            (self._menu_label("&Commit"), "commit_files"),
            (self._menu_label("&Quit"), "quit"),
        ]

    def _name_width(self) -> int:
        fallback = LONG_NAME_WIDTH if self.file_list_mode == MODE_LONG else SHORT_NAME_WIDTH
        try:
            status_list = self.query_one("#status_list", StatusList)
        except WIDGET_LOOKUP_ERRORS:
            return fallback

        content_region = getattr(status_list, "content_region", None)
        content_width = getattr(content_region, "width", None)
        if not isinstance(content_width, int):
            return fallback

        row_text_width = content_width - STATUS_LIST_ITEM_HORIZONTAL_PADDING
        if row_text_width <= 0:
            return fallback

        fixed_width = STATUS_WIDTH + SIZE_WIDTH + MTIME_WIDTH + (3 * COLUMN_GAP)
        return max(1, row_text_width - fixed_width)

    def _column_header_text(self, name_width: int | None = None) -> str:
        name_width = self._name_width() if name_width is None else name_width
        return (
            f"{'Status':<{STATUS_WIDTH}}  "
            f"{'Name':<{name_width}}  "
            f"{'Size':>{SIZE_WIDTH}}  "
            f"{'Modify time':>{MTIME_WIDTH}}"
        )

    # ------------------------------------------------------------------
    # Git reads (thread workers)
    #
    # Every git read that grows with the repo runs on a `@work(thread=True)`
    # worker: doing it inline blocks Textual's event loop, which freezes the
    # whole UI until the subprocess returns. Each one is a trio — a launcher
    # on the UI thread, a worker that only fetches, and an `_apply_*` that
    # only renders, reached via `call_from_thread`.
    # ------------------------------------------------------------------

    def _new_request(self, group: str) -> int:
        """Issue a serial identifying the newest request in *group*.

        Why: `exclusive=True` cancels the asyncio task of a superseded worker,
        but a *thread* worker keeps running to completion, so two results for
        the same group can arrive in either order. Each `_apply_*` drops a
        result whose serial is no longer current, so the newest request always
        wins regardless of which git call finishes first.
        """
        serial = self._request_serials.get(group, 0) + 1
        self._request_serials[group] = serial
        return serial

    def _is_current_request(self, group: str, serial: int) -> bool:
        return self._request_serials.get(group) == serial

    def _load_commits(self) -> None:
        """Reload the history list. `git log` runs on a worker thread."""
        self._load_commits_worker(serial=self._new_request("history"))

    @work(thread=True, exclusive=True, group="git-history")
    def _load_commits_worker(self, *, serial: int) -> None:
        commits = self.git.load_commits()
        self.call_from_thread(self._apply_commits, commits=commits, serial=serial)

    def _apply_commits(self, *, commits: list[Commit], serial: int) -> None:
        if not self._is_current_request("history", serial):
            return
        self.commits = commits
        list_view = self.query_one("#commit_list", CommitList)
        list_view.clear()
        for commit in self.commits:
            short_hash = commit.hash[:7]
            list_view.append(
                ListItem(Label(f"[bold]{short_hash}[/bold]  {commit.date}  {commit.subject}"))
            )

    def _load_status(
        self,
        *,
        restore: GitEntry | None = None,
        refocus: bool = False,
        clear_diff: bool = True,
    ) -> None:
        """Reload the file list. `git status` runs on a worker thread.

        Why: on a repo of any size `git status` plus the per-submodule branch
        lookups take long enough to stall Textual's event loop, which freezes
        keyboard and mouse input until they return.
        How to apply: pass *restore* instead of calling
        `_schedule_restore_selection` after the call — the reload is now
        asynchronous, so a restore issued at the call site would run against
        the pre-reload list. *refocus* is forwarded to that restore.
        """
        self._load_status_worker(
            serial=self._new_request("status"),
            previous_selections=set(self.status_filelist.selected_filenames),
            collapse_untracked_dirs=self.file_list_filter == FILTER_UNTRACKED_DIRS,
            restore=restore,
            refocus=refocus,
            clear_diff=clear_diff,
        )

    @work(thread=True, exclusive=True, group="git-status")
    def _load_status_worker(
        self,
        *,
        serial: int,
        previous_selections: set[str],
        collapse_untracked_dirs: bool,
        restore: GitEntry | None,
        refocus: bool,
        clear_diff: bool,
    ) -> None:
        """Off-thread half of `_load_status`: fetch only, touch no widgets."""
        filelist = self.git.load_status(collapse_untracked_dirs=collapse_untracked_dirs)
        mismatches = self.git.submodule_branch_mismatches()
        self.call_from_thread(
            self._apply_status,
            serial=serial,
            filelist=filelist,
            previous_selections=previous_selections,
            mismatches=mismatches,
            restore=restore,
            refocus=refocus,
            clear_diff=clear_diff,
        )

    def _apply_status(
        self,
        *,
        serial: int,
        filelist: GitFilelist,
        previous_selections: set[str],
        mismatches: list[tuple[str, str | None, str | None]],
        restore: GitEntry | None = None,
        refocus: bool = False,
        clear_diff: bool = True,
    ) -> None:
        """UI-thread half of `_load_status`: render what the worker fetched."""
        if not self._is_current_request("status", serial):
            return
        self.status_filelist = filelist
        self.status_filelist.restore_selections(previous_selections)
        self._submodule_mismatches = mismatches
        if clear_diff:
            file_diff = self.query_one("#file-diff", FileDiff)
            file_diff.display = False
            file_diff.border_title = ""
        self._render_status_rows()
        if restore is not None:
            self._schedule_restore_selection(restore, refocus_active_view=refocus)

    def _render_status_rows(self) -> None:
        list_view = self.query_one("#status_list", StatusList)
        list_view.clear()
        name_width = self._name_width()
        self.query_one("#column-header", Label).update(self._column_header_text(name_width))
        ui_theme = self._active_ui_theme()
        row_texts = self.status_filelist.row_texts(
            self.repo_path,
            status_width=STATUS_WIDTH,
            name_width=name_width,
            size_width=SIZE_WIDTH,
            mtime_width=MTIME_WIDTH,
            status_colors=ui_theme.status_color_map(),
            submodule_color=ui_theme.status_submodule,
        )
        for index, row_text in enumerate(row_texts):
            classes = "selected" if self.status_filelist.is_selected(index) else ""
            list_view.append(StatusListItem(Label(row_text), classes=classes))
        self._update_submodule_warnings()
        self._update_status_header()

    def _update_submodule_warnings(self) -> None:
        """Render the cached submodule/parent branch mismatches.

        Reads `_submodule_mismatches` rather than querying git: this runs on
        every re-render, including resize-driven ones, and each mismatch check
        is a `git rev-parse` per submodule.
        """
        try:
            label = self.query_one("#submodule-warnings", Label)
        except WIDGET_LOOKUP_ERRORS:
            return
        mismatches = self._submodule_mismatches
        if not mismatches:
            label.update("")
            label.add_class("empty")
            return
        style = self._active_ui_theme().warning_text
        lines: list[str] = []
        for sub_path, sub_branch, parent_branch in mismatches:
            text = f"Warning: {_submodule_mismatch_text(sub_path, sub_branch, parent_branch)}"
            lines.append(f"[{style}]{text}[/{style}]" if style else text)
        label.update("\n".join(lines))
        label.remove_class("empty")

    def _update_status_header(self) -> None:
        try:
            header = self.query_one("#status-header", Label)
        except WIDGET_LOOKUP_ERRORS:
            return
        message = self.status_filelist.status_message()
        # Before the entry's description, whose length changes with every
        # row, so the filter state stays in one place on the line.
        message = f"{message} | {FILE_LIST_FILTER_LABELS[self.file_list_filter]}"
        entry = self.status_filelist.highlighted_entry
        if entry is not None:
            message = f"{message} | {entry.code.long_description}"
        header.update(message)

    def _toggle_status_selection(self, index: int) -> None:
        """Toggle selection at *index* in the file list.

        Why: CTRL+click lives on the item but the selection state lives on
        `GitFilelist`, so the item delegates back to the app.
        How to apply: called from StatusListItem._on_click (CTRL branch).
        """
        self.status_filelist.toggle_selection(index)
        self._apply_selection_classes()

    def _toggle_current_status_selection(self) -> None:
        """Space key: toggle selection on the currently-highlighted row.

        Unlike SHIFT+arrow, this does NOT move the cursor — the user stays
        on the row so they can immediately see whether they selected or
        deselected it.
        """
        try:
            list_view = self.query_one("#status_list", StatusList)
        except WIDGET_LOOKUP_ERRORS:
            return
        idx = list_view.index
        if not isinstance(idx, int):
            return
        self.status_filelist.toggle_selection(idx)
        self._apply_selection_classes()

    def _extend_status_selection(self, delta: int) -> None:
        """SHIFT+arrow: toggle current row, then move cursor by *delta*."""
        try:
            list_view = self.query_one("#status_list", StatusList)
        except WIDGET_LOOKUP_ERRORS:
            return
        idx = list_view.index
        if not isinstance(idx, int):
            return
        self.status_filelist.toggle_selection(idx)
        new_idx = idx + delta
        if 0 <= new_idx < len(self.status_filelist):
            list_view.index = new_idx
        self._apply_selection_classes()

    def _apply_selection_classes(self) -> None:
        try:
            list_view = self.query_one("#status_list", StatusList)
        except WIDGET_LOOKUP_ERRORS:
            return
        children = getattr(list_view, "children", None) or []
        for index, child in enumerate(children):
            is_selected = self.status_filelist.is_selected(index)
            add = getattr(child, "add_class", None)
            remove = getattr(child, "remove_class", None)
            if is_selected and callable(add):
                add("selected")
            elif callable(remove):
                remove("selected")

    def _refresh_status_layout(self) -> None:
        """Re-render the status list using the cached filelist.

        Why: resize events must re-flow the Size / Modify time columns so
        they stay flush to the right edge of the list, but must not re-run
        git status on every resize.
        How to apply: called from StatusList.on_resize; safe to no-op if the
        DOM isn't ready (first mount, teardown).
        """
        try:
            self.query_one("#status_list", StatusList)
        except WIDGET_LOOKUP_ERRORS:
            return
        current_entry = self._current_status_entry()
        self._render_status_rows()
        if current_entry is not None:
            self._schedule_restore_selection(current_entry)

    def on_list_view_highlighted(self, event) -> None:
        if event.list_view.id != "status_list":
            return
        self.status_filelist.set_highlighted_index(event.list_view.index)
        self._update_status_header()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if event.list_view.id == "status_list":
            entry = self.status_filelist.set_highlighted_index(index)
            if entry is None:
                return
            self._last_status_entry = entry
            if self.file_list_mode == MODE_LONG:
                self.query_one(ContentSwitcher).current = "diff-view"
                self._render_entry_into("diff-full", entry)
            else:
                self._render_entry_into("file-diff", entry)
            return
        if event.list_view.id != "commit_list":
            return
        if index is None or index >= len(self.commits):
            return
        commit = self.commits[index]
        meta = self.query_one("#meta", Label)
        meta.update(f"[bold]{commit.hash[:7]}[/bold]  {commit.author}  {commit.date}")
        self._load_commit_detail(commit.hash)

    def _load_commit_detail(self, commit_hash: str) -> None:
        """Show the diff for *commit_hash*; `git show` runs on a worker thread."""
        self._load_commit_detail_worker(
            commit_hash=commit_hash, serial=self._new_request("commit-detail")
        )

    @work(thread=True, exclusive=True, group="git-commit-detail")
    def _load_commit_detail_worker(self, *, commit_hash: str, serial: int) -> None:
        detail_text = self.git.show_commit(commit_hash)
        self.call_from_thread(self._apply_commit_detail, detail_text=detail_text, serial=serial)

    def _apply_commit_detail(self, *, detail_text: str, serial: int) -> None:
        if not self._is_current_request("commit-detail", serial):
            return
        self.query_one("#detail", CommitDetail).show(detail_text)

    def on_key(self, event) -> None:
        """Navigate between menus with left/right arrows while one is open.

        A nested menu has no neighbours to cycle through, so there left means
        "back": it reopens the menu the submenu was opened from, the same way
        Escape does.

        Dialog keys are not handled here: each dialog is a ModalScreen that
        owns its own keys, and Textual stops the binding chain at the modal
        (see `Screen._modal_binding_chain`), so no key can reach this app
        while one is open.
        """
        if self._open_menu_for_accelerator(event):
            return
        if event.key not in ("left", "right"):
            return
        if event.key == "left" and self._close_submenu_to_parent():
            event.stop()
            return
        current = self._open_menu_index()
        if current == -1:
            return
        event.stop()
        delta = 1 if event.key == "right" else -1
        self._show_menu_by_index((current + delta) % len(self.MENU_ORDER))

    def on_click(self, event) -> None:
        """Close open menus when clicking outside them."""
        node = event.widget
        while node is not None:
            if isinstance(node, (DropdownMenu, MenuBar)):
                return
            node = node.parent
        self.action_close_menus()

    # ------------------------------------------------------------------
    # Menu helpers
    # ------------------------------------------------------------------

    def _open_menu_for_accelerator(self, event) -> bool:
        """Open the menu whose highlighted letter *event* names.

        Alt+letter is the Turbo Vision way into a menu bar, and it works both
        from the app and while another menu is already open.
        """
        prefix = "alt+"
        if not event.key.startswith(prefix):
            return False
        char = event.key[len(prefix) :]
        if len(char) != 1:
            return False
        for index, (label, _) in enumerate(MENU_BAR):
            if _menu_mnemonic_key(label) == char.lower():
                event.stop()
                self._show_menu_by_index(index)
                return True
        return False

    def _open_menu_index(self) -> int:
        """Return the index of the currently visible dropdown, or -1."""
        for i, menu_id in enumerate(self.MENU_ORDER):
            if self.query_one(f"#{_dropdown_id(menu_id)}", DropdownMenu).display:
                return i
        return -1

    def _open_submenu(self) -> Submenu | None:
        """The nested menu that is currently open, if any."""
        registered = {submenu.dropdown_id: submenu for submenu in SUBMENUS}
        for dropdown in self.query(DropdownMenu):
            if dropdown.display and dropdown.id in registered:
                return registered[dropdown.id]
        return None

    def _close_submenu_to_parent(self) -> bool:
        """Reopen the parent of the open nested menu; False when none is open.

        A nested menu is reached through its parent, so both ways out of it —
        Escape and left — put that parent back on screen with the cursor on
        the entry that opened the submenu, rather than dropping the user out
        of the menus altogether.
        """
        submenu = self._open_submenu()
        if submenu is None or submenu.parent_id not in self.MENU_ORDER:
            return False
        self._show_menu_by_index(self.MENU_ORDER.index(submenu.parent_id))
        try:
            parent = self.query_one(f"#{_dropdown_id(submenu.parent_id)}", DropdownMenu)
        except WIDGET_LOOKUP_ERRORS:
            return True
        parent.highlight_action(submenu.action)
        return True

    def _refresh_dropdown(self, menu_id: str) -> None:
        if menu_id == "menu_file":
            self.query_one("#dropdown_file", DropdownMenu).set_items(self._file_menu_items())

    def _show_menu_by_index(self, index: int) -> None:
        """Close all menus and open the one at *index*."""
        menu_id = self.MENU_ORDER[index]
        self._refresh_dropdown(menu_id)
        label = self.query_one(f"#{menu_id}", MenuLabel)
        region = label.region
        for dd in self.query(DropdownMenu):
            dd.hide()
        for ml in self.query(MenuLabel):
            ml.remove_class("-active")
        label.add_class("-active")
        self.query_one(f"#{_dropdown_id(menu_id)}", DropdownMenu).show_at(region.x, region.y + 1)

    def toggle_menu(self, menu_id: str, x: int, y: int) -> None:
        self._refresh_dropdown(menu_id)
        target = self.query_one(f"#{_dropdown_id(menu_id)}", DropdownMenu)
        if target.display:
            # Every dropdown, not just this one: a cascading submenu is open
            # alongside its parent and would be left behind on its own.
            for dd in self.query(DropdownMenu):
                dd.hide()
            self.query_one(f"#{menu_id}", MenuLabel).remove_class("-active")
        else:
            for dd in self.query(DropdownMenu):
                dd.hide()
            for ml in self.query(MenuLabel):
                ml.remove_class("-active")
            self.query_one(f"#{menu_id}", MenuLabel).add_class("-active")
            target.show_at(x, y)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_menu(self) -> None:
        """F9: open the first menu."""
        self._show_menu_by_index(0)

    def action_quit(self) -> None:  # type: ignore[override]
        """F10: quit, killing any git read still in flight first.

        Why: the reads run on thread workers, and a thread worker can only be
        waited for — Textual joins them during shutdown. So F10 pressed while
        the startup `git status` / `git log` are still running registered
        fine but changed nothing on screen until git returned, which on a
        large repo is seconds of an app that looks like it ignored the key.
        Ending the subprocesses ends the workers with it.

        A pull or push in flight is left alone: it is a write, half of it is
        on the wire, and the user asked to close the app rather than to
        cancel the command. That quit waits, the way every quit used to.
        """
        if not self._remote_running:
            self.git.shutdown()
        self.exit()

    def action_refresh(self) -> None:
        self.action_close_menus()
        switcher = self.query_one(ContentSwitcher)
        if switcher.current == "status-view" or switcher.current == "diff-view":
            self._load_status()
        else:
            self._load_commits()
        self.notify("Refreshed")

    def action_view_status(self) -> None:
        self.action_close_menus()
        self._load_status()
        self.query_one(ContentSwitcher).current = "status-view"

    def action_view_history(self) -> None:
        self.action_close_menus()
        self.query_one(ContentSwitcher).current = "history-view"

    def action_short_file_list(self) -> None:
        self.action_close_menus()
        self._set_file_list_mode(MODE_SHORT)

    def action_toggle_file_list(self) -> None:
        """F3: flip between the short and long file-list presentations.

        The two modes are a visually unmistakable binary (inline diff panel vs.
        full-width list), so one key covers both directions. The File menu still
        offers each mode as its own entry for an unambiguous direct set.

        F3 is the Norton Commander / MC "view" key, matching the F2/F9/F10
        bindings this app already uses. The previous Ctrl+S / Ctrl+W pair was
        unsafe: Ctrl+S is XOFF flow control (the same reason 8b9c467 moved
        commit-save to F2) and Ctrl+W is werase in the shell this app spawns
        for Ctrl+O, as well as close-tab in browser-hosted terminals.
        """
        if self.file_list_mode == MODE_LONG:
            self.action_short_file_list_inline_diff()
        else:
            self.action_long_file_list_full_screen_diff()

    def action_short_file_list_inline_diff(self) -> None:
        """Switch to short mode, carrying an open full-screen diff
        back to the inline panel next to the file list."""
        self.action_close_menus()
        if self.file_list_mode == MODE_LONG:
            entry = self._diff_entry_if_full_screen_visible()
            if entry is not None:
                self._move_diff_between_modes(MODE_SHORT, entry)
                return
        self._set_file_list_mode(MODE_SHORT)

    def action_long_file_list_full_screen_diff(self) -> None:
        """Switch to long mode, carrying the inline diff on to the
        full-screen view — but only when that diff is what the user is
        looking at.

        The inline panel stays visible after Enter opens a diff, so "a diff
        is on screen" is not enough to tell "expand this diff" from "widen
        the list": with the focus back on the file list, F3 has to mean the
        mode switch it advertises. Focus is read before the menus close,
        because closing them hands focus back to the active view.
        """
        entry = self._focused_inline_diff_entry() if self.file_list_mode == MODE_SHORT else None
        self.action_close_menus()
        if entry is not None:
            self._move_diff_between_modes(MODE_LONG, entry)
            return
        self._set_file_list_mode(MODE_LONG)

    def action_long_file_list(self) -> None:
        self.action_close_menus()
        self._set_file_list_mode(MODE_LONG)

    def action_toggle_file_filter(self) -> None:
        """f: step to the next quick filter of the file list."""
        self.action_close_menus()
        index = FILE_LIST_FILTERS.index(self.file_list_filter)
        self._set_file_list_filter(FILE_LIST_FILTERS[(index + 1) % len(FILE_LIST_FILTERS)])

    def action_file_filter_none(self) -> None:
        self.action_close_menus()
        self._set_file_list_filter(FILTER_NONE)

    def action_file_filter_untracked_dirs(self) -> None:
        self.action_close_menus()
        self._set_file_list_filter(FILTER_UNTRACKED_DIRS)

    def _set_file_list_filter(self, file_filter: str) -> None:
        """Apply *file_filter* and reload the file list under it.

        The full-screen diff is left because the file it shows may be one the
        new filter folds into its directory; the highlight follows the file
        to that directory's row (see `GitFilelist.index_of`).
        """
        selected_entry = self._current_status_entry() or self._last_status_entry
        self.file_list_filter = file_filter
        self._update_status_header()
        self._leave_diff_view()
        self._load_status(restore=selected_entry)

    def _set_file_list_mode(self, mode: str) -> None:
        selected_entry = self._current_status_entry() or self._last_status_entry
        self.file_list_mode = mode
        status_view = self.query_one("#status-view")
        if mode == MODE_LONG:
            status_view.add_class("long-mode")
        else:
            status_view.remove_class("long-mode")
        self._leave_diff_view()
        self._load_status(restore=selected_entry)

    def _move_diff_between_modes(self, target_mode: str, entry: GitEntry) -> None:
        """Switch file-list mode while keeping the open diff visible, moving
        it from inline↔full-screen as appropriate."""
        self._last_status_entry = entry
        self.file_list_mode = target_mode
        status_view = self.query_one("#status-view")
        if target_mode == MODE_LONG:
            status_view.add_class("long-mode")
        else:
            status_view.remove_class("long-mode")
        # clear_diff=False: the status reload and the diff render are separate
        # workers, so letting the reload blank the panel would race the diff
        # we are deliberately carrying across the mode switch.
        self._load_status(restore=entry, clear_diff=False)
        switcher = self.query_one(ContentSwitcher)
        if target_mode == MODE_LONG:
            switcher.current = "diff-view"
            self._render_entry_into("diff-full", entry)
        else:
            switcher.current = "status-view"
            self.query_one("#diff-full", FileDiff).border_title = ""
            self._render_entry_into("file-diff", entry)

    def _render_entry_into(self, widget_id: str, entry: GitEntry) -> None:
        """Show *entry* in the FileDiff with *widget_id*, as a diff or, for an
        untracked file, as raw content. Reads the file/diff off the UI thread.

        Takes an id rather than the widget itself because the read is deferred:
        the widget is re-queried when the text comes back.
        """
        self._render_entry_worker(
            widget_id=widget_id, entry=entry, serial=self._new_request("diff")
        )

    @work(thread=True, exclusive=True, group="git-diff")
    def _render_entry_worker(self, *, widget_id: str, entry: GitEntry, serial: int) -> None:
        if entry.code.is_untracked:
            text = self.git.load_file_content(entry)
        else:
            text = self.git.load_file_diff(entry)
        self.call_from_thread(
            self._apply_entry_diff, widget_id=widget_id, entry=entry, text=text, serial=serial
        )

    def _apply_entry_diff(self, *, widget_id: str, entry: GitEntry, text: str, serial: int) -> None:
        if not self._is_current_request("diff", serial):
            return
        try:
            widget = self.query_one(f"#{widget_id}", FileDiff)
        except WIDGET_LOOKUP_ERRORS:
            return
        if entry.code.is_untracked:
            widget.show_content(text, entry.filename)
        else:
            widget.show(text, entry.filename)

    def _current_status_entry(self) -> GitEntry | None:
        status_list = self.query_one("#status_list", StatusList)
        return self.status_filelist.entry_at(status_list.index)

    def _restore_status_selection(self, entry: GitEntry) -> None:
        index = self.status_filelist.index_of(entry)
        if index is None:
            return
        self._last_status_entry = self.status_filelist.set_highlighted_index(index)
        status_list = self.query_one("#status_list", StatusList)
        old_index = status_list.index
        status_list.index = index
        if old_index == index:
            # Textual only runs watch_index when the reactive value changes.
            # When returning from diff-view, the list can already be on the
            # right row but have lost the visual highlight class.
            status_list.watch_index(old_index, index)

    def _schedule_restore_selection(
        self, entry: GitEntry, *, refocus_active_view: bool = False
    ) -> None:
        """Defer highlight restoration until after the list is re-rendered.

        Why: _load_status() calls ListView.clear() + append(), but Textual
        processes the prune messages asynchronously, so the cleared items
        linger in _nodes alongside the new ones. Setting list_view.index
        synchronously lands the -highlight class on a dying old item, and
        the matching new row is never highlighted.
        How to apply: call this instead of _restore_status_selection after
        any _load_status() / _render_status_rows() that rebuilt the list.
        """
        restore = (
            self._restore_status_selection_and_focus
            if refocus_active_view
            else self._restore_status_selection
        )
        self.call_after_refresh(restore, entry)

    def _restore_status_selection_and_focus(self, entry: GitEntry) -> None:
        self._restore_status_selection(entry)
        self._focus_active_view_unless_dialog()

    def _focus_active_view_unless_dialog(self) -> None:
        """Refocus the active view unless a dialog is on top of it.

        This runs deferred (via call_after_refresh), and the commit flow opens
        the message dialog from inside the confirm callback — so by the time
        it fires, a dialog screen may already own the focus.
        """
        try:
            on_dialog = isinstance(self.screen, ModalScreen)
        except NO_SCREEN_ERRORS:
            on_dialog = False
        if not on_dialog:
            self._focus_active_view()

    def _focused_inline_diff_entry(self) -> GitEntry | None:
        """The highlighted entry, but only while the inline diff panel is
        both visible and the focused widget."""
        inline_diff = self.query_one("#file-diff", FileDiff)
        if not inline_diff.display:
            return None
        try:
            focused = self.focused
        except NO_SCREEN_ERRORS:
            return None
        if focused is not inline_diff:
            return None
        return self._current_status_entry()

    def _diff_entry_if_full_screen_visible(self) -> GitEntry | None:
        if self.query_one(ContentSwitcher).current != "diff-view":
            return None
        return self._current_status_entry()

    def _leave_diff_view(self) -> None:
        switcher = self.query_one(ContentSwitcher)
        entry = self._current_status_entry() or self._last_status_entry
        if switcher.current == "diff-view":
            switcher.current = "status-view"
        self.query_one("#diff-full", FileDiff).border_title = ""
        if entry is not None:
            self._restore_status_selection(entry)

    def action_stage_file(self) -> None:
        """S: ask before running `git add`. If multiple files are selected,
        batch-stage every selected file that has unstaged changes; otherwise
        fall back to the single highlighted file."""
        self.action_close_menus()
        selected = self.status_filelist.selected_entries()
        if selected:
            eligible = [e for e in selected if e.code.has_unstaged_changes]
            if not eligible:
                self.notify("No selected files have unstaged changes")
                return
            commands = [" ".join(self.git.stage_command_for(e)) for e in eligible]
            self._show_confirm(
                f"Stage {len(eligible)} file(s)?",
                commands,
                lambda: self._run_stage_batch(eligible),
            )
            return
        entry = self._current_status_entry()
        if entry is None:
            return
        if not entry.code.has_unstaged_changes:
            self.notify(f"{entry.filename} has no unstaged changes")
            return
        command = " ".join(self.git.stage_command_for(entry))
        self._show_confirm(
            f"Stage {entry.filename}?",
            [command],
            lambda: self._run_stage(entry),
        )

    def action_unstage_file(self) -> None:
        """U: ask before running `git restore --staged`. If multiple files are
        selected, batch-unstage every selected file that has staged changes;
        otherwise fall back to the single highlighted file."""
        self.action_close_menus()
        selected = self.status_filelist.selected_entries()
        if selected:
            eligible = [e for e in selected if e.code.has_staged_changes]
            if not eligible:
                self.notify("No selected files have staged changes")
                return
            commands = [" ".join(self.git.unstage_command_for(e)) for e in eligible]
            self._show_confirm(
                f"Unstage {len(eligible)} file(s)?",
                commands,
                lambda: self._run_unstage_batch(eligible),
            )
            return
        entry = self._current_status_entry()
        if entry is None:
            return
        if not entry.code.has_staged_changes:
            self.notify(f"{entry.filename} has no staged changes")
            return
        command = " ".join(self.git.unstage_command_for(entry))
        self._show_confirm(
            f"Unstage {entry.filename}?",
            [command],
            lambda: self._run_unstage(entry),
        )

    def action_restore_file(self) -> None:
        """F7: ask before resetting file(s) to their HEAD state.

        Covers every status where a restore has a well-defined meaning:
        modified/deleted/typechange/renamed/copied (staged or unstaged)
        become a single `git restore --source=HEAD --staged --worktree`;
        added-in-index become `git restore --staged` + `git clean -f`;
        untracked become `git clean -f`. Ignored and unmerged files are
        filtered out because restoring them isn't unambiguous.
        """
        self.action_close_menus()
        selected = self.status_filelist.selected_entries()
        if selected:
            eligible = [e for e in selected if e.code.is_restorable]
            if not eligible:
                self.notify("No selected files can be restored")
                return
            commands: list[str] = []
            for entry in eligible:
                for argv in self.git.restore_commands(entry):
                    commands.append(" ".join(argv))
            self._show_confirm(
                f"Restore {len(eligible)} file(s) to HEAD?",
                commands,
                lambda: self._run_restore_batch(eligible),
            )
            return
        entry = self._current_status_entry()
        if entry is None:
            return
        if not entry.code.is_restorable:
            self.notify(f"{entry.filename} cannot be restored")
            return
        commands = [" ".join(argv) for argv in self.git.restore_commands(entry)]
        self._show_confirm(
            f"Restore {entry.filename} to HEAD?",
            commands,
            lambda: self._run_restore(entry),
        )

    def action_delete_file(self) -> None:
        """DELETE: ask before removing file(s).

        Files are grouped by status code in the confirmation dialog, with
        the operation that runs for that status shown once per group above
        the affected filenames. The command shape comes from
        `git.delete_commands` so the dialog and the executor stay in sync.
        """
        self.action_close_menus()
        selected = self.status_filelist.selected_entries()
        if selected:
            eligible = [e for e in selected if e.code.is_deletable]
            multi = True
        else:
            entry = self._current_status_entry()
            eligible = [entry] if entry is not None and entry.code.is_deletable else []
            multi = False
        if not eligible:
            self.notify("No files can be deleted")
            return
        groups: dict[GitCode, list[GitEntry]] = {}
        for entry in eligible:
            groups.setdefault(entry.code, []).append(entry)
        commands = self._format_delete_groups(groups)
        prompt = f"Delete {len(eligible)} file(s)?" if multi else f"Delete {eligible[0].filename}?"
        self._show_confirm(
            prompt,
            commands,
            lambda: self._run_delete_batch(eligible),
        )

    def _format_delete_groups(self, groups: dict[GitCode, list[GitEntry]]) -> list[str]:
        """Render one section per status group for the confirm dialog."""
        lines: list[str] = []
        for index, (code, entries) in enumerate(groups.items()):
            if index > 0:
                lines.append("")
            lines.append(f"-- {code.long_description} --")
            sample_name = self.git.entry_command_filename(entries[0])
            for argv in self.git.delete_commands(entries[0]):
                template = ["<file>" if part == sample_name else part for part in argv]
                lines.append(f"  {' '.join(template)}")
            for entry in entries:
                lines.append(f"  {entry.filename}")
        return lines

    def _show_confirm(
        self,
        prompt: str,
        commands: list[str],
        on_confirm: Callable[[], None],
        on_cancel: Callable[[], object] | None = None,
        *,
        fill_height: bool = False,
    ) -> None:
        """Ask for Y/N confirmation, running `on_confirm` only if confirmed.

        N (or Esc) hands focus back to the active view unless `on_cancel` says
        otherwise — the commit confirmation uses it to reopen the message
        dialog instead of throwing the message away.

        `fill_height` lets the command list grow to the screen height (see
        `ConfirmDialog`); the commit prompts use it to show every file.
        """

        def resolved(confirmed: bool | None) -> None:
            if confirmed:
                on_confirm()
            elif on_cancel is not None:
                on_cancel()
            else:
                self._focus_active_view()

        self.push_screen(
            ConfirmDialog(prompt=prompt, commands=commands, fill_height=fill_height),
            callback=resolved,
        )

    def _run_stage(self, entry: GitEntry) -> None:
        result = self.git.stage_entry(entry)
        self._report_git_result(result, f"Staged {entry.filename}", "git add failed")
        self._reload_status_keeping_selection(entry)

    def _run_unstage(self, entry: GitEntry) -> None:
        result = self.git.unstage_entry(entry)
        self._report_git_result(result, f"Unstaged {entry.filename}", "git restore --staged failed")
        self._reload_status_keeping_selection(entry)

    def _run_restore(self, entry: GitEntry) -> None:
        results = self.git.restore_file(entry)
        failed = next((r for r in results if getattr(r, "returncode", 0) != 0), None)
        if failed is not None:
            stderr = (getattr(failed, "stderr", "") or "").strip()
            detail = f": {stderr}" if stderr else ""
            self.notify(f"git restore failed{detail}")
        else:
            self.notify(f"Restored {entry.filename}")
        self._reload_status_keeping_selection(entry)

    def _run_restore_batch(self, entries: list[GitEntry]) -> None:
        failures: list[str] = []
        for entry in entries:
            results = self.git.restore_file(entry)
            if any(getattr(r, "returncode", 0) != 0 for r in results):
                failures.append(entry.filename)
        if failures:
            self.notify(f"git restore failed for {len(failures)} file(s): {', '.join(failures)}")
        else:
            self.notify(f"Restored {len(entries)} file(s)")
        self._load_status(restore=self._current_status_entry())

    def _run_delete_batch(self, entries: list[GitEntry]) -> None:
        failures: list[str] = []
        for entry in entries:
            results = self.git.delete_file(entry)
            if any(getattr(r, "returncode", 0) != 0 for r in results):
                failures.append(entry.filename)
        if failures:
            self.notify(f"delete failed for {len(failures)} file(s): {', '.join(failures)}")
        else:
            self.notify(f"Deleted {len(entries)} file(s)")
        self._load_status(restore=self._current_status_entry())

    def _run_stage_batch(self, entries: list[GitEntry]) -> None:
        self._run_git_batch(entries, self.git.stage_entry, "Staged", "git add")

    def _run_unstage_batch(self, entries: list[GitEntry]) -> None:
        self._run_git_batch(entries, self.git.unstage_entry, "Unstaged", "git restore --staged")

    def _run_git_batch(
        self,
        entries: list[GitEntry],
        run_one: Callable[[GitEntry], object],
        success_verb: str,
        failure_prefix: str,
    ) -> None:
        failures: list[str] = []
        for entry in entries:
            result = run_one(entry)
            if getattr(result, "returncode", 0) != 0:
                failures.append(entry.filename)
        if failures:
            self.notify(
                f"{failure_prefix} failed for {len(failures)} file(s): {', '.join(failures)}"
            )
        else:
            self.notify(f"{success_verb} {len(entries)} file(s)")
        self._load_status(restore=self._current_status_entry())

    def _report_git_result(self, result, success_message: str, failure_prefix: str) -> None:
        returncode = getattr(result, "returncode", 0)
        if returncode != 0:
            stderr = (getattr(result, "stderr", "") or "").strip()
            detail = f": {stderr}" if stderr else ""
            self.notify(f"{failure_prefix}{detail}")
        else:
            self.notify(success_message)

    def _reload_status_keeping_selection(self, entry: GitEntry) -> None:
        self._load_status(restore=entry, refocus=True)

    def action_commit_files(self) -> None:
        """C: commit the highlighted file or every selected file.

        The flow:
          1. Determine the target files (selection, or highlighted fallback).
          2. If any target has unstaged changes, open a Y/N confirm with the
             `git add` commands that would stage them.
          3. After (optional) stage confirmation, unstage any files that are
             currently staged but NOT in the commit selection (recorded so
             they can be re-staged later).
          4. Show a multi-line commit message dialog, prefilled with the
             branch name when `branch_prefix_in_commits` is enabled.
          5. On submit: confirm the commit, showing every command it will
             run, and only then run them and restore the previously-staged
             externals. On Esc: undo both index changes step 2 and 3 made —
             restore the externals and unstage what we staged — so a
             cancelled commit leaves the index exactly as it found it.
        """
        self.action_close_menus()

        targets = self.status_filelist.selected_entries()
        if not targets:
            entry = self._current_status_entry()
            if entry is None:
                self.notify("Nothing to commit")
                return
            targets = [entry]

        committable = [
            e for e in targets if e.code.has_staged_changes or e.code.has_unstaged_changes
        ]
        if not committable:
            self.notify("No changes to commit in selection")
            return

        to_stage = [e for e in targets if e.code.has_unstaged_changes]
        target_filenames = {e.filename for e in targets}
        # A submodule whose inner files we're committing will have its gitlink
        # re-staged automatically by commit_with_selection — never unstage it
        # as an "external" or we'd lose the pointer bump.
        selected_subs = {e.submodule for e in targets if e.submodule}
        externals = sorted(
            f for f in self.git.staged_filenames() - target_filenames if f not in selected_subs
        )

        # Only entries whose index state we create from nothing can be rolled
        # back on cancel: an entry that already had staged changes was staged
        # *partially*, and `git restore --staged` would throw that away rather
        # than put it back.
        undo_stage = [e for e in to_stage if not e.code.has_staged_changes]

        def proceed() -> None:
            for entry in to_stage:
                self.git.stage_entry(entry)
            for filename in externals:
                self.git.unstage_file(filename)
            self._begin_commit_message(targets, externals, staged=undo_stage)

        if to_stage:
            commands = [" ".join(self.git.stage_command_for(e)) for e in to_stage]
            self._show_confirm(
                f"Stage {len(to_stage)} file(s) for commit?",
                commands,
                proceed,
                fill_height=True,
            )
            return
        proceed()

    def _begin_commit_message(
        self, targets: list[GitEntry], externals: list[str], staged: list[GitEntry] | None = None
    ) -> None:
        """Open the multi-line commit message dialog after staging is resolved.

        `staged` are the entries this flow just staged and would have to
        unstage again if the commit is cancelled.
        """
        self._pending_commit_externals = list(externals)
        self._pending_commit_staged = list(staged or [])
        self._pending_commit_targets = list(targets)
        branch = self._commit_branch_prefix()
        prefill = f"{branch}: " if branch else ""
        self._edit_commit_message(prefill)

    def _edit_commit_message(self, message: str) -> None:
        """Open `message` in the editor the settings name, and hand the
        result on to `_commit_result` as the commit dialog would.

        The built-in dialog is also the fallback whenever the external editor
        can't be used — not configured after all, or a terminal that can't be
        handed over — so the commit the user started is never lost to a
        setting.
        """
        argv = self._commit_editor_argv()
        if argv is not None and self._commit_in_external_editor(argv=argv, message=message):
            return
        self.push_screen(CommitDialog(prefill=message), callback=self._commit_result)

    def _commit_editor_argv(self) -> list[str] | None:
        """The external editor's command line, split the way a shell would,
        or None for the built-in dialog.

        A setting that names an external editor without one — $EDITOR unset,
        an empty or unparseable command — says so and falls back to the
        dialog.
        """
        settings = self._load_settings()
        editor = _setting_str(settings, "commit_editor", COMMIT_EDITOR_BUILTIN)
        if editor == COMMIT_EDITOR_ENVIRONMENT:
            command = os.environ.get("EDITOR", "")
            missing = "$EDITOR is not set"
        elif editor == COMMIT_EDITOR_COMMAND:
            command = _setting_str(settings, "commit_editor_command", "")
            missing = "No editor command configured (Options → Settings)"
        else:
            return None
        if not command.strip():
            self.notify(f"{missing}; using the built-in editor")
            return None
        try:
            return shlex.split(command)
        except ValueError:
            self.notify(f"Could not read the editor command: {command}; using the built-in editor")
            return None

    def _commit_in_external_editor(self, *, argv: list[str], message: str) -> bool:
        """Edit the commit message in `argv` on the previous screen.

        The app is suspended for the length of the edit, the way `Ctrl+O`
        suspends it for a shell. An empty message — or one that is nothing
        but the branch prefix it was opened with — cancels the commit, as
        does an editor that exits with a failure status; git reads both the
        same way.

        Returns False when nothing was edited — the terminal can't be
        suspended, or the editor couldn't be started — and the caller opens
        the built-in dialog instead. Only entering the suspension is guarded,
        as in `_draft_on_previous_screen()`.
        """
        filenames = [entry.filename for entry in self._pending_commit_targets]
        with ExitStack() as suspension:
            try:
                suspension.enter_context(self.suspend())
            except (OSError, SuspendNotSupported, RuntimeError):
                # RuntimeError: an app with no driver declines to suspend by
                # never yielding.
                self.notify("Can't hand the terminal to an editor here; using the built-in editor")
                return False
            edited = run_commit_editor(
                argv=argv, message=message, filenames=filenames, cwd=self.repo_path
            )
        if not edited.started:
            self.notify(f"{edited.detail}; using the built-in editor")
            return False
        if edited.message is None:
            self.notify(edited.detail)
            self._commit_result(None)
            return True
        branch = self._commit_branch_prefix()
        if not edited.message or (branch and edited.message == f"{branch}:"):
            self._commit_result(None)
            return True
        self._commit_result(edited.message)
        return True

    def _commit_branch_prefix(self) -> str:
        """The branch name commit messages are prefixed with, or "" when the
        setting is off (or the branch can't be read)."""
        settings = self._load_settings()
        if not bool(settings.get("branch_prefix_in_commits", False)):
            return ""
        return self.git.branch_name() or ""

    def _with_branch_prefix(self, message: str) -> str:
        """`message` with the branch prefix put in front of it when the
        setting asks for one and the message doesn't already carry it.

        A drafting tool knows nothing about that setting, so what it hands
        back has to be prefixed here — unless it happened to open with the
        branch name anyway, e.g. because the prompt told it to.
        """
        branch = self._commit_branch_prefix()
        if not branch or message.startswith(branch):
            return message
        return f"{branch}: {message}"

    def request_commit_draft(self, dialog: CommitDialog) -> None:
        """Draft button / F4 in the commit dialog: run the configured tool.

        It is invoked as `<command> <prompt>` — the command line from the
        settings split the way a shell would, with the prompt template and
        the files being committed handed over as one final argument.

        The run happens on the previous screen, exactly where `Ctrl+O` puts
        a shell: there is no UI to keep responsive while the app is
        suspended, so it runs inline. A terminal that can't be suspended
        falls back to the worker, which runs the same tool off the UI thread
        with only the dialog's log to show for it.
        """
        settings = self._load_settings()
        command = _setting_str(settings, "commit_draft_command", COMMIT_DRAFT_COMMAND_DEFAULT)
        if not command.strip():
            self.notify("No commit message tool configured (Options → Settings)")
            return
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        if not argv:
            self.notify(f"Could not read the commit message tool command: {command}")
            return
        template = _setting_str(settings, "commit_draft_prompt", COMMIT_DRAFT_PROMPT_DEFAULT)
        filenames = [entry.filename for entry in self._pending_commit_targets]
        prompt = commit_draft_prompt(template, filenames)
        dialog.set_drafting(True)
        if self._draft_on_previous_screen(dialog=dialog, argv=argv, prompt=prompt):
            return
        self._commit_draft_worker(dialog=dialog, argv=argv, prompt=prompt)

    def _draft_on_previous_screen(
        self, *, dialog: CommitDialog, argv: list[str], prompt: str
    ) -> bool:
        """Run the drafting tool on the previous screen, as `Ctrl+O` does.

        The tool is the one thing this app runs that has something to say
        while it works, so it says it on the terminal the TUI was started
        from rather than into a six-row pane: the app is suspended for the
        length of the run and every line is echoed as it is read. What it
        printed is still on that screen afterwards, so `Ctrl+O` from the main
        screen scrolls back to the whole run long after the commit.

        Showing the output doesn't give up capturing it — the lines are still
        parsed into the commit message, or the reason there isn't one — but
        the screen is the only place they are *shown*. The dialog's log pane
        stays empty and hidden on this path: the user has just watched the
        whole run, and repeating it under the message box is noise around the
        one thing the dialog is for.

        Returns False when the terminal can't be suspended: nothing has run
        at that point, and the caller falls back to the worker. Only entering
        the suspension is guarded — a stack rather than a plain `with` — so
        that a failure inside the run can't be read as "never suspended" and
        send the same tool off to the worker for a second run.
        """

        def echo(line: str) -> None:
            self._screen.write_previous_screen(f"{line}\n")

        with ExitStack() as suspension:
            try:
                suspension.enter_context(self.suspend())
            except (OSError, SuspendNotSupported, RuntimeError):
                # RuntimeError is the context manager never yielding, which
                # is how an app with no driver — one that isn't running —
                # declines to suspend.
                return False
            # The command line as a shell would show it, so what ran is part
            # of the scrollback and not just its output.
            self._screen.write_previous_screen(f"$ {shlex.join([*argv, prompt])}\n")
            drafted = run_commit_draft(argv=argv, prompt=prompt, cwd=self.repo_path, on_output=echo)
            self._screen.write_previous_screen("\n")
        self._apply_commit_draft(dialog=dialog, drafted=drafted)
        return True

    @work(thread=True, exclusive=True, group="commit-draft")
    def _commit_draft_worker(self, *, dialog: CommitDialog, argv: list[str], prompt: str) -> None:
        """The fallback for a terminal that can't be suspended: the same run
        with the TUI still on screen, so it has to stay off the UI thread and
        the dialog's log is the only place the output shows."""
        drafted = run_commit_draft(
            argv=argv,
            prompt=prompt,
            cwd=self.repo_path,
            on_output=lambda line: self._post_draft_output(dialog=dialog, line=line),
        )
        self.call_from_thread(self._apply_commit_draft, dialog=dialog, drafted=drafted)

    def _post_draft_output(self, *, dialog: CommitDialog, line: str) -> None:
        """Hand one line of the tool's output to the dialog from the worker.

        Reached from the worker thread and from the stderr reader inside
        `run_commit_draft`, so it goes through `call_from_thread` like every
        other worker result. A run that outlives the app — the user quit
        while the tool was still going — has nowhere to put the line, and
        dropping it is the whole of the recovery.
        """
        try:
            self.call_from_thread(dialog.append_output, line)
        except RuntimeError:
            pass

    def _apply_commit_draft(self, *, dialog: CommitDialog, drafted: DraftResult) -> None:
        """Put what the tool produced into the commit dialog.

        With "Parse suggestions from numbered list" on, the output is read as
        a numbered list first: more than one item opens the picker, exactly
        one goes straight in (there is nothing to choose between), and none
        falls back to the whole output — a tool that ignored the request for
        a list still wrote something, and dropping it would be worse than
        handing it over.
        """
        dialog.set_drafting(False)
        if not drafted.ok:
            self.notify(drafted.text)
            return
        if self._parse_suggestions_enabled():
            suggestions = parse_numbered_suggestions(drafted.text)
            if len(suggestions) > 1:
                self.push_screen(
                    SuggestionDialog(suggestions),
                    callback=lambda picked: self._apply_commit_suggestion(
                        dialog=dialog, picked=picked
                    ),
                )
                return
            if suggestions:
                dialog.set_text(self._with_branch_prefix(suggestions[0]))
                return
            self.notify("No numbered suggestions found; using the whole output")
        dialog.set_text(self._with_branch_prefix(drafted.text))

    def _parse_suggestions_enabled(self) -> bool:
        return bool(self._load_settings().get("commit_draft_parse_suggestions", False))

    def _apply_commit_suggestion(self, *, dialog: CommitDialog, picked: str | None) -> None:
        """Picker callback: load the choice into the message, or leave the
        message alone when the user backed out. Either way the drafting tool's
        output is still in the dialog's log, so nothing is lost by cancelling.
        """
        if picked is None:
            return
        dialog.set_text(self._with_branch_prefix(picked))

    def _restore_externals(self) -> None:
        for filename in self._pending_commit_externals:
            self.git.stage_file(filename)
        self._pending_commit_externals = []

    def _unstage_pending(self) -> None:
        """Undo the `git add`s this commit flow ran (cancel path only).

        Without this the files stay staged, and a second `C` on the same
        selection sees nothing left to stage — so the "Stage N file(s) for
        commit?" question never comes back after a cancelled commit.
        """
        for entry in self._pending_commit_staged:
            self.git.unstage_entry(entry)
        self._pending_commit_staged = []

    def _commit_result(self, message: str | None) -> None:
        """Dialog callback: a message means confirm-then-commit, None means
        the user cancelled and the externals we unstaged must go back."""
        if message is None:
            self._commit_cancel()
        else:
            self._confirm_commit(message)

    def _confirm_commit(self, message: str) -> None:
        """Show what the commit will run and ask before running it.

        This is the last point at which the files going into the commit are
        visible — after it, `commit_with_selection` walks the submodules and
        commits. The command list comes from `commit_with_selection_commands`
        so the popup and the executor can't drift apart, with the message
        shortened to its subject line: the popup lists commands one per row,
        and a multi-line `-m` argument would break that.

        N reopens the message dialog on the message just written rather than
        dropping it, so backing out of the confirmation costs nothing.
        """
        targets = list(self._pending_commit_targets)
        preview = _commit_message_subject(message)
        commands = [
            " ".join(argv) for argv in self.git.commit_with_selection_commands(targets, preview)
        ]
        self._show_confirm(
            f"Commit {len(targets)} file(s)?",
            commands,
            lambda: self._commit_submit(message),
            lambda: self._edit_commit_message(message),
            fill_height=True,
        )

    def _commit_submit(self, message: str) -> None:
        result = self.git.commit_with_selection(self._pending_commit_targets, message)
        self._pending_commit_targets = []
        self._pending_commit_staged = []
        self._restore_externals()
        returncode = getattr(result, "returncode", 0)
        if returncode != 0:
            stderr = (getattr(result, "stderr", "") or "").strip()
            detail = f": {stderr}" if stderr else ""
            self.notify(f"git commit failed{detail}")
        else:
            self.notify("Committed")
        self._load_status()
        self._load_commits()
        self._focus_active_view()

    def _commit_cancel(self) -> None:
        self._pending_commit_targets = []
        self._unstage_pending()
        self._restore_externals()
        self._load_status()
        self.notify("Commit cancelled")
        self._focus_active_view()

    def action_clear_selection(self) -> None:
        """Ctrl+U: clear all file selections in the status view."""
        self.action_close_menus()
        if self.query_one(ContentSwitcher).current != "status-view":
            return
        if not self.status_filelist.selected_filenames:
            return
        self.status_filelist.clear_selections()
        self._apply_selection_classes()

    # ------------------------------------------------------------------
    # Stash and remote commands
    #
    # All four ask first, for the same reason the file commands do: the
    # confirmation is the last place the exact command line is visible, and
    # each of these moves work the user cannot see from the file list —
    # `stash` empties the worktree, `stash pop` refills it (and can conflict),
    # `pull` moves HEAD, and `push` is the one that leaves the machine. What
    # none of them get is a second, free-text prompt: a stash message or a
    # remote to choose is a shell's job, and Ctrl+O is next to these keys.
    # ------------------------------------------------------------------

    def action_stash(self) -> None:
        """z: ask before `git stash push`.

        A selection stashes those files and nothing else; with nothing
        selected the whole worktree goes, because "stash the file under the
        cursor" is not what anyone reaches for stash to do. Submodule entries
        drop out of a path-limited stash — the pathspec would name a path in
        another repository — and the dialog says how many were left behind.
        """
        self.action_close_menus()
        if not self.status_filelist:
            self.notify("Nothing to stash")
            return
        selected = self.status_filelist.selected_entries()
        filenames: list[str] | None = None
        prompt = "Stash all changes?"
        notes: list[str] = []
        if selected:
            eligible = [entry for entry in selected if entry.submodule is None]
            if not eligible:
                self.notify("Cannot stash files inside a submodule")
                return
            filenames = [entry.filename for entry in eligible]
            prompt = f"Stash {len(filenames)} file(s)?"
            skipped = len(selected) - len(eligible)
            if skipped:
                notes = ["", f"-- {skipped} file(s) inside a submodule are left alone --"]
        command = " ".join(self.git.stash_command(filenames=filenames))
        self._show_confirm(
            prompt,
            [command, *notes],
            lambda: self._run_stash(filenames=filenames),
        )

    def _run_stash(self, *, filenames: list[str] | None) -> None:
        result = self.git.stash(filenames=filenames)
        self._report_git_result(result, "Stashed changes", "git stash failed")
        self._load_status()

    def action_stash_pop(self) -> None:
        """Shift+Z: ask before `git stash pop`.

        The prompt names the entry that would be reapplied rather than saying
        "the stash": which one is on top is exactly what a user who stashed
        twice can't remember. An empty stash is reported instead of opening a
        dialog over a command that would only fail.
        """
        self.action_close_menus()
        entries = self.git.stash_entries()
        if not entries:
            self.notify("No stash entries to pop")
            return
        notes: list[str] = []
        if len(entries) > 1:
            notes = ["", f"-- {len(entries)} entries stashed; pop takes the newest --"]
        command = " ".join(self.git.stash_pop_command())
        self._show_confirm(
            f"Pop {_truncate_to_width(entries[0], STASH_PROMPT_MAX_WIDTH)}?",
            [command, *notes],
            self._run_stash_pop,
        )

    def _run_stash_pop(self) -> None:
        result = self.git.stash_pop()
        self._report_git_result(result, "Popped the newest stash entry", "git stash pop failed")
        self._load_status()

    def action_pull(self) -> None:
        """p: ask before `git pull --ff-only`.

        Both refusals ahead of the dialog are things git would only report
        after the fact: with no remote there is nothing to pull from, and
        without an upstream `--ff-only` has no ref to fast-forward to.
        """
        self.action_close_menus()
        if not self._remote_available():
            return
        upstream = self.git.upstream_branch()
        if upstream is None:
            branch = self.git.branch_name() or "HEAD"
            self.notify(f"{branch} has no upstream branch — push it first (Shift+P)")
            return
        command = " ".join(self.git.pull_command())
        self._show_confirm(
            f"Pull from {upstream}?",
            [command, *self._submodule_mismatch_notes()],
            self._run_pull,
        )

    def action_push(self) -> None:
        """Shift+P: ask before `git push`.

        The prompt distinguishes the two shapes `push_command` can take,
        because pushing a branch that has no upstream publishes it on the
        remote for the first time — a bigger step than updating one that is
        already there, and the only place to say so is the question.
        """
        self.action_close_menus()
        if not self._remote_available():
            return
        command = " ".join(self.git.push_command())
        branch = self.git.branch_name() or "HEAD"
        upstream = self.git.upstream_branch()
        if upstream is None:
            remote = next(iter(self.git.remote_names()), "the remote")
            prompt = f"Push {branch} to {remote} and set it as upstream?"
        else:
            prompt = f"Push {branch} to {upstream}?"
        self._show_confirm(
            prompt,
            [command, *self._submodule_mismatch_notes()],
            self._run_push,
        )

    def _submodule_mismatch_notes(self) -> list[str]:
        """Warning rows for the pull/push confirmations, one per submodule
        that is on a branch of its own.

        Why these two commands get them: both move the parent's history past
        a gitlink that points into a submodule nobody is on the branch of, so
        what comes back from the remote — or what the remote is now told the
        submodule should be at — is a commit the checked-out submodule branch
        may not contain. The status view already says so in its warning
        label, but the confirmation is the last thing between the keypress
        and the network, and it is the one place the user is reading.

        Read from the `_submodule_mismatches` cache the status worker fills,
        like `_update_submodule_warnings` and for the same reason: the check
        is a `git rev-parse` per submodule, and this runs on the UI thread
        while a dialog is being built.
        """
        if not self._submodule_mismatches:
            return []
        notes = [""]
        notes += [
            f"-- Warning: {_submodule_mismatch_text(sub_path, sub_branch, parent_branch)} --"
            for sub_path, sub_branch, parent_branch in self._submodule_mismatches
        ]
        return notes

    def _remote_available(self) -> bool:
        """False (with the reason notified) when a network command can't run."""
        if self._remote_running:
            self.notify("A pull or push is already running")
            return False
        if not self.git.remote_names():
            self.notify("No remote is configured for this repository")
            return False
        return True

    def _run_pull(self) -> None:
        self._start_remote_command(label="Pull", run=self.git.pull)

    def _run_push(self) -> None:
        self._start_remote_command(label="Push", run=self.git.push)

    def _start_remote_command(
        self,
        *,
        label: str,
        run: Callable[[], subprocess.CompletedProcess[str]],
    ) -> None:
        """Run a network git command on a thread worker.

        The other writes (`git add`, `git rm`) run inline because they return
        in milliseconds. A pull or push sits on the network instead, and
        inline it would freeze every key in the TUI until it came back — the
        same reason the reads moved onto workers.
        """
        self._remote_running = True
        self.notify(f"{label} in progress…")
        self._remote_worker(label=label, run=run)

    @work(thread=True, group="git-remote")
    def _remote_worker(
        self,
        *,
        label: str,
        run: Callable[[], subprocess.CompletedProcess[str]],
    ) -> None:
        try:
            result = run()
        except OSError as exc:
            result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=str(exc))
        self.call_from_thread(self._apply_remote_result, label=label, result=result)

    def _apply_remote_result(self, *, label: str, result: subprocess.CompletedProcess[str]) -> None:
        """Report a finished pull/push and reload both views from disk."""
        self._remote_running = False
        failed = getattr(result, "returncode", 0) != 0
        summary = _remote_result_summary(result, failed=failed)
        if failed:
            self.notify(f"{label} failed: {summary}" if summary else f"{label} failed")
        else:
            self.notify(f"{label}: {summary}" if summary else f"{label} finished")
        self._load_status()
        self._load_commits()

    def action_settings(self) -> None:
        self.action_close_menus()
        settings = self._load_settings()
        self.push_screen(
            SettingsDialog(
                branch_prefix=bool(settings.get("branch_prefix_in_commits", False)),
                draft_command=_setting_str(
                    settings, "commit_draft_command", COMMIT_DRAFT_COMMAND_DEFAULT
                ),
                draft_prompt=_setting_str(
                    settings, "commit_draft_prompt", COMMIT_DRAFT_PROMPT_DEFAULT
                ),
                default_branch=_setting_str(settings, "default_branch", DEFAULT_BRANCH_DEFAULT),
                parse_suggestions=bool(settings.get("commit_draft_parse_suggestions", False)),
                editor=_setting_str(settings, "commit_editor", COMMIT_EDITOR_BUILTIN),
                editor_command=_setting_str(settings, "commit_editor_command", ""),
            ),
            callback=self._settings_result,
        )

    def _settings_result(self, values: SettingsValues | None) -> None:
        """Dialog callback: values on save, None when the user pressed Esc."""
        self._focus_active_view()
        if values is None:
            return
        settings = self._load_settings()
        settings["branch_prefix_in_commits"] = values.branch_prefix
        settings["commit_draft_command"] = values.draft_command
        settings["commit_draft_prompt"] = values.draft_prompt
        settings["default_branch"] = values.default_branch
        settings["commit_draft_parse_suggestions"] = values.parse_suggestions
        settings["commit_editor"] = values.editor
        settings["commit_editor_command"] = values.editor_command
        if not self._save_settings(settings):
            self.notify("Settings saved (could not write to disk)")
        else:
            self.notify("Settings saved")

    def action_open_submenu(self, name: str) -> None:
        """Open the nested menu registered as *name* (Options → Theme, ...).

        The submenu cascades out of the row that opens it: the parent menu
        stays on screen with its cursor on that row, and the child hangs off
        its right edge with its own first row on the same line. The parent
        dropdown was hidden by the OptionList handler that invoked this
        action, so it is put back before the child is placed against it.
        """
        submenu = SUBMENUS_BY_NAME.get(name)
        if submenu is None:
            return
        try:
            label = self.query_one(f"#{submenu.parent_id}", MenuLabel)
            parent = self.query_one(f"#{_dropdown_id(submenu.parent_id)}", DropdownMenu)
            dropdown = self.query_one(f"#{submenu.dropdown_id}", DropdownMenu)
        except WIDGET_LOOKUP_ERRORS:
            return
        for dd in self.query(DropdownMenu):
            if dd is not parent:
                dd.hide()
        region = label.region
        parent_x, parent_y = region.x, region.y + 1
        parent.show_at(parent_x, parent_y)
        parent.highlight_action(submenu.action)
        # Both menus have a top border above their first entry, so the two
        # cancel out: putting the child's top `row` lines below the parent's
        # lands the child's first entry on the parent's row.
        row = parent.index_of_action(submenu.action) or 0
        x = self._cascade_x(
            left=parent_x, parent_width=parent.menu_width, width=dropdown.menu_width
        )
        dropdown.show_at(x, parent_y + row)

    def _cascade_x(self, *, left: int, parent_width: int, width: int) -> int:
        """Where a cascading submenu starts.

        Off the parent's right edge, or off its left one when that would run
        the submenu past the right edge of the screen.
        """
        x = left + parent_width
        try:
            screen_width = self.screen.size.width
        except WIDGET_LOOKUP_ERRORS:
            return x
        if screen_width and x + width > screen_width:
            return max(0, left - width)
        return x

    def action_set_theme(self, theme_name: str) -> None:
        self.action_close_menus()
        try:
            self.theme = theme_name
        except InvalidThemeError as exc:
            self.notify(f"Could not set theme: {exc}")
            return
        self._restyle_menu_mnemonics()
        settings = self._load_settings()
        settings["theme"] = theme_name
        if not self._save_settings(settings):
            self.notify("Theme updated, but could not save settings")
            return
        self.notify(f"Theme: {theme_name}")

    def _restyle_menu_mnemonics(self) -> None:
        """Re-render every menu label in the active theme's accelerator style.

        Menu chrome is built once and stays mounted, so unlike the diff views
        it would otherwise keep the accelerator colors of the theme that was
        active when it was composed. A theme can also be restored before the
        DOM exists (`_load_saved_theme`), which is what the guard is for.
        """
        try:
            labels = list(self.query(MenuLabel))
            dropdowns = list(self.query(DropdownMenu))
        except WIDGET_LOOKUP_ERRORS:
            return
        for label in labels:
            label.apply_mnemonic_style()
        for dropdown in dropdowns:
            dropdown.apply_mnemonic_style()

    def action_keys(self) -> None:
        """F1 / Help → Keys: show the keyboard shortcut reference."""
        self.action_close_menus()
        self.push_screen(HelpDialog(shortcuts=HELP_SHORTCUTS), callback=self._help_closed)

    def _help_closed(self, _result: None) -> None:
        self._focus_active_view()

    def action_screenshot(self, *args, **kwargs) -> None:
        """Override Textual's built-in screenshot action so screenshots
        cannot be triggered from this app."""
        self.notify("Screenshots are disabled")

    def action_toggle_previous_screen(self) -> None:
        try:
            with self.suspend():
                self._screen.run_previous_screen_session()
        except (OSError, SuspendNotSupported):
            self.notify("Previous-screen toggle is not supported in this terminal")

    def action_escape(self) -> None:
        """ESCAPE: close an open menu, else exit full-screen diff.

        A nested menu closes back to the menu that opened it, so Escape
        walks out one level at a time instead of leaving the menus entirely.

        Dialogs are not handled here — each is a ModalScreen that dismisses
        itself on Esc, and this binding cannot fire while one is open.
        """
        if self._close_submenu_to_parent():
            return
        any_open = False
        for dd in self.query(DropdownMenu):
            if dd.display:
                dd.hide()
                any_open = True
        for ml in self.query(MenuLabel):
            ml.remove_class("-active")
        if any_open:
            self._focus_active_view()
            return
        self._leave_diff_view()
        self._focus_active_view()

    def action_close_menus(self) -> None:
        for dd in self.query(DropdownMenu):
            dd.hide()
        for ml in self.query(MenuLabel):
            ml.remove_class("-active")
        self._focus_active_view()

    def _focus_active_view(self) -> None:
        current = self.query_one(ContentSwitcher).current
        if current == "status-view":
            self.query_one("#status_list", StatusList).focus()
        elif current == "history-view":
            self.query_one("#commit_list", CommitList).focus()
        elif current == "diff-view":
            self.query_one("#diff-full", FileDiff).focus()
