import asyncio
import io
import json
import re
import sys
import tempfile
import threading
import types
import unittest
from collections.abc import Callable
from contextlib import contextmanager
from functools import partial, wraps
from pathlib import Path
from typing import Any, Self
from unittest.mock import MagicMock, PropertyMock, patch


def _install_textual_stubs() -> None:
    rich: Any = types.ModuleType("rich")
    rich_text: Any = types.ModuleType("rich.text")
    textual: Any = types.ModuleType("textual")
    textual_app: Any = types.ModuleType("textual.app")
    textual_binding: Any = types.ModuleType("textual.binding")
    textual_containers: Any = types.ModuleType("textual.containers")
    textual_message: Any = types.ModuleType("textual.message")
    textual_screen: Any = types.ModuleType("textual.screen")
    textual_widget: Any = types.ModuleType("textual.widget")
    textual_widgets: Any = types.ModuleType("textual.widgets")
    textual_option_list: Any = types.ModuleType("textual.widgets.option_list")
    textual_theme: Any = types.ModuleType("textual.theme")
    textual_css: Any = types.ModuleType("textual.css")
    textual_css_query: Any = types.ModuleType("textual.css.query")
    textual_types: Any = types.ModuleType("textual.types")

    class Text(str):
        pass

    def work(method=None, **kwargs):
        """Stand-in for `textual.work`. The real decorator wraps the method so
        that calling it schedules `self.run_worker(...)`; the stub keeps that
        shape so `run_worker` stays the seam tests control."""

        def decorator(func):
            @wraps(func)
            def decorated(self, *args, **inner_kwargs):
                return self.run_worker(partial(func, self, *args, **inner_kwargs), **kwargs)

            return decorated

        return decorator if method is None else decorator(method)

    class SuspendNotSupported(Exception):
        pass

    # Exception types app.py narrows its defensive handlers to. Real Textual
    # raises these; the stubs only need the names to exist and be catchable.
    class QueryError(Exception):
        pass

    class ScreenStackError(Exception):
        pass

    class NoActiveAppError(Exception):
        pass

    class InvalidThemeError(Exception):
        pass

    class App:
        def __init__(self, *args, **kwargs):
            self._registered_themes = {}

        @contextmanager
        def suspend(self):
            yield

        @property
        def focused(self):
            """Real App.focused is the active screen's focused widget. The
            stub has no DOM, so nothing is focused until a test patches it."""
            return None

        def register_theme(self, theme):
            self._registered_themes[getattr(theme, "name", "")] = theme

        def notify(self, *args, **kwargs):
            pass

        def call_after_refresh(self, callback, *args, **kwargs):
            callback(*args, **kwargs)

        def run_worker(self, work, **kwargs):
            """Real run_worker schedules `work` on a Textual worker. The stub
            runs it inline; _mock_app() overrides this the same way when the
            real Textual is installed."""
            return work()

        def call_from_thread(self, callback, *args, **kwargs):
            """Real call_from_thread hands the callback to the app's event
            loop from a worker thread. Under the stubs there is no loop and no
            thread, so call it directly."""
            return callback(*args, **kwargs)

        def query_one(self, *args, **kwargs):
            # There is no DOM under the stubs. Raise what real Textual raises
            # for a missing widget so app.py's narrowed handlers still match.
            raise QueryError("no DOM in stubbed Textual")

        def query(self, *args, **kwargs):
            raise QueryError("no DOM in stubbed Textual")

        @property
        def screen(self):
            # Real Textual raises this when the screen stack is empty, which
            # is the state a non-running app is always in.
            raise ScreenStackError("no screen under stubbed Textual")

        def push_screen(self, screen, callback=None, **kwargs):
            """Real push_screen mounts the screen and calls `callback` with
            whatever it dismisses with. Tests replace this with a MagicMock
            and drive the callback themselves."""
            return

    class ComposeResult:
        pass

    class Binding:
        def __init__(self, *args, **kwargs):
            self.key = args[0] if len(args) > 0 else kwargs.get("key")
            self.action = args[1] if len(args) > 1 else kwargs.get("action")
            self.description = args[2] if len(args) > 2 else kwargs.get("description")
            self.show = kwargs.get("show", True)
            self.key_display = kwargs.get("key_display")
            self.priority = kwargs.get("priority", False)

    class Widget:
        def __init__(self, *args, **kwargs):
            self.id = kwargs.get("id")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        @property
        def app(self):
            # Real Textual raises this for a widget with no running app, and
            # app.py's dialogs rely on catching it to fall back to a default
            # theme while unmounted.
            raise NoActiveAppError("no app under stubbed Textual")

        @property
        def parent(self):
            # Real MessagePump.parent dereferences the weakref it keeps in
            # `_MessagePump__parent`; tests plant one there to mount an item
            # under a fake list, so read the same slot.
            parent_ref = getattr(self, "_MessagePump__parent", None)
            return None if parent_ref is None else parent_ref()

        def query_one(self, *args, **kwargs):
            raise QueryError("no DOM in stubbed Textual")

    class Screen(Widget):
        AUTO_FOCUS = None

        def dismiss(self, result=None):
            """Real dismiss pops the screen and fires the push_screen
            callback. Tests that care patch this with a MagicMock."""
            return result

    class ModalScreen(Screen):
        def __class_getitem__(cls, item):
            # ModalScreen[bool] — the result type is erased under the stubs.
            return cls

    class Message:
        def __init__(self, *args, **kwargs):
            pass

    class Static(Widget):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.value = args[0] if args else ""

    class Label(Static):
        pass

    class Footer(Widget):
        pass

    class Header(Widget):
        pass

    class ListItem(Widget):
        pass

    class ListView(Widget):
        class Selected:
            pass

    class OptionList(Widget):
        class OptionSelected:
            pass

    class ContentSwitcher(Widget):
        pass

    class Horizontal(Widget):
        pass

    class ScrollableContainer(Widget):
        pass

    class Vertical(Widget):
        pass

    class SelectionList(Widget):
        pass

    class Button(Widget):
        def __init__(self, *args, **kwargs):
            super().__init__(**{k: v for k, v in kwargs.items() if k in ("id",)})
            self.label = args[0] if args else ""
            self.disabled = False

    class Checkbox(Widget):
        def __init__(self, *args, **kwargs):
            super().__init__(**{k: v for k, v in kwargs.items() if k in ("id",)})
            self.value = False

    class TextArea(Widget):
        def __init__(self, *args, **kwargs):
            super().__init__(**{k: v for k, v in kwargs.items() if k in ("id",)})
            self.text = args[0] if args else ""

        def load_text(self, text):
            self.text = text

        def move_cursor(self, location):
            pass

        def focus(self):
            pass

    class Option:
        def __init__(self, *args, **kwargs):
            pass

    class Theme:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get("name", args[0] if args else "")

    rich_text.Text = Text
    textual.work = work
    textual_app.App = App
    textual_app.ComposeResult = ComposeResult
    textual_app.SuspendNotSupported = SuspendNotSupported
    textual_binding.Binding = Binding
    textual_binding.BindingType = Binding
    textual_containers.Horizontal = Horizontal
    textual_containers.ScrollableContainer = ScrollableContainer
    textual_containers.Vertical = Vertical
    textual_message.Message = Message
    textual_screen.Screen = Screen
    textual_screen.ModalScreen = ModalScreen
    textual_widget.Widget = Widget
    textual_widgets.Button = Button
    textual_widgets.ContentSwitcher = ContentSwitcher
    textual_widgets.Footer = Footer
    textual_widgets.Header = Header
    textual_widgets.Label = Label
    textual_widgets.ListItem = ListItem
    textual_widgets.ListView = ListView
    textual_widgets.OptionList = OptionList
    textual_widgets.SelectionList = SelectionList
    textual_widgets.Checkbox = Checkbox
    textual_widgets.Static = Static
    textual_widgets.TextArea = TextArea
    textual_option_list.Option = Option
    textual_theme.Theme = Theme
    textual_app.InvalidThemeError = InvalidThemeError
    textual_app.ScreenStackError = ScreenStackError
    textual_css_query.QueryError = QueryError
    textual_types.NoActiveAppError = NoActiveAppError

    sys.modules["rich"] = rich
    sys.modules["rich.text"] = rich_text
    sys.modules["textual"] = textual
    sys.modules["textual.app"] = textual_app
    sys.modules["textual.binding"] = textual_binding
    sys.modules["textual.containers"] = textual_containers
    sys.modules["textual.message"] = textual_message
    sys.modules["textual.screen"] = textual_screen
    sys.modules["textual.widget"] = textual_widget
    sys.modules["textual.widgets"] = textual_widgets
    sys.modules["textual.widgets.option_list"] = textual_option_list
    sys.modules["textual.theme"] = textual_theme
    sys.modules["textual.css"] = textual_css
    sys.modules["textual.css.query"] = textual_css_query
    sys.modules["textual.types"] = textual_types


try:
    from gitnc.app import (
        COMMIT_DRAFT_COMMAND_DEFAULT,
        COMMIT_DRAFT_OUTPUT_LINES,
        COMMIT_DRAFT_PROMPT_DEFAULT,
        CONFIRM_DIALOG_CHROME_WIDTH,
        CONFIRM_DIALOG_MIN_TEXT_WIDTH,
        CONFIRM_DIALOG_SCROLLBAR_WIDTH,
        CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS,
        DEFAULT_BRANCH_DEFAULT,
        HELP_MENU,
        HELP_SHORTCUTS,
        MENU_BAR,
        MENU_HINTS_BY_ACTION,
        MENU_MARKER_BLANK,
        MENU_MARKER_GAP,
        MENU_RADIO_OFF,
        MENU_RADIO_ON,
        MENU_SUBMENU_MARKER,
        MIDNIGHT_COMMANDER_THEME,
        MIDNIGHT_COMMANDER_THEME_NAME,
        MODE_LONG,
        MODE_SHORT,
        MTIME_WIDTH,
        OPTIONS_MENU,
        REPO_MENU,
        SETTINGS_FIELD_MAX_LINES,
        SETTINGS_FIELD_MIN_LINES,
        SETTINGS_FIELD_TEXT_WIDTH,
        SETTINGS_ROW_COUNT,
        SETTINGS_ROW_PARSE,
        SETTINGS_ROW_PROMPT,
        SETTINGS_SECTION_WIDTH,
        SHORTCUT_ALIASES,
        SHORTCUTS,
        SIZE_WIDTH,
        STATUS_WIDTH,
        SUBMENUS,
        SUBMENUS_BY_NAME,
        THEMES,
        TRUNCATION_MARKER,
        VIEW_MENU,
        CommitDetail,
        CommitDialog,
        CommitTextArea,
        ConfirmDialog,
        DraftResult,
        DropdownMenu,
        FieldLine,
        FileDiff,
        GitNightCommanderApp,
        MenuLabel,
        SettingsDialog,
        SettingsValues,
        StatusList,
        StatusListItem,
        SuggestionDialog,
        SuspendNotSupported,
        _menu_hint,
        _menu_mnemonic_key,
        _menu_option_labels,
        _menu_option_markup,
        _menu_plain_label,
        _strip_markup,
        _truncate_to_width,
        _wrap_field_text,
        commit_draft_prompt,
        parse_numbered_suggestions,
        render_commit_detail,
        run_commit_draft,
    )
    from gitnc.git import GitCode, GitEntry, GitFilelist
    from gitnc.terminal import Terminal
except ModuleNotFoundError as exc:
    if exc.name not in {"rich", "textual"}:
        raise
    sys.modules.pop("gitnc.app", None)
    _install_textual_stubs()
    from gitnc.app import (
        COMMIT_DRAFT_COMMAND_DEFAULT,
        COMMIT_DRAFT_OUTPUT_LINES,
        COMMIT_DRAFT_PROMPT_DEFAULT,
        CONFIRM_DIALOG_CHROME_WIDTH,
        CONFIRM_DIALOG_MIN_TEXT_WIDTH,
        CONFIRM_DIALOG_SCROLLBAR_WIDTH,
        CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS,
        DEFAULT_BRANCH_DEFAULT,
        HELP_MENU,
        HELP_SHORTCUTS,
        MENU_BAR,
        MENU_HINTS_BY_ACTION,
        MENU_MARKER_BLANK,
        MENU_MARKER_GAP,
        MENU_RADIO_OFF,
        MENU_RADIO_ON,
        MENU_SUBMENU_MARKER,
        MIDNIGHT_COMMANDER_THEME,
        MIDNIGHT_COMMANDER_THEME_NAME,
        MODE_LONG,
        MODE_SHORT,
        MTIME_WIDTH,
        OPTIONS_MENU,
        REPO_MENU,
        SETTINGS_FIELD_MAX_LINES,
        SETTINGS_FIELD_MIN_LINES,
        SETTINGS_FIELD_TEXT_WIDTH,
        SETTINGS_ROW_COUNT,
        SETTINGS_ROW_PARSE,
        SETTINGS_ROW_PROMPT,
        SETTINGS_SECTION_WIDTH,
        SHORTCUT_ALIASES,
        SHORTCUTS,
        SIZE_WIDTH,
        STATUS_WIDTH,
        SUBMENUS,
        SUBMENUS_BY_NAME,
        THEMES,
        TRUNCATION_MARKER,
        VIEW_MENU,
        CommitDetail,
        CommitDialog,
        CommitTextArea,
        ConfirmDialog,
        DraftResult,
        DropdownMenu,
        FieldLine,
        FileDiff,
        GitNightCommanderApp,
        MenuLabel,
        SettingsDialog,
        SettingsValues,
        StatusList,
        StatusListItem,
        SuggestionDialog,
        SuspendNotSupported,
        _menu_hint,
        _menu_mnemonic_key,
        _menu_option_labels,
        _menu_option_markup,
        _menu_plain_label,
        _strip_markup,
        _truncate_to_width,
        _wrap_field_text,
        commit_draft_prompt,
        parse_numbered_suggestions,
        render_commit_detail,
        run_commit_draft,
    )
    from gitnc.git import GitCode, GitEntry, GitFilelist
    from gitnc.terminal import Terminal

from textual.screen import ModalScreen

from gitnc import app as _app_module

# The rich stub is a bare `str` subclass with no styling API, so the tests
# that assert which style each rendered run carries only run against real rich.
_TEXT_RECORDS_STYLES = hasattr(_app_module.Text, "append")


class TestGitNightCommanderApp(unittest.TestCase):
    def test_quit_binding_uses_f10(self):
        """F10 is the primary key — what the footer, the menu hint and the
        README advertise. `q` aliases it (see
        `test_quit_is_reachable_by_f10_and_q`) and comes after it."""
        quit_bindings = [
            binding
            for binding in GitNightCommanderApp.BINDINGS
            if getattr(binding, "action", None) == "quit"
        ]
        self.assertEqual(getattr(quit_bindings[0], "key", None), "f10")
        self.assertTrue(getattr(quit_bindings[0], "show", False))

    def test_action_toggle_previous_screen_suspends_until_ctrl_o(self):
        app = GitNightCommanderApp()

        @contextmanager
        def fake_suspend():
            yield

        with (
            patch.object(app, "suspend", return_value=fake_suspend()) as suspend,
            patch.object(Terminal, "run_previous_screen_session") as run_session,
        ):
            app.action_toggle_previous_screen()

        suspend.assert_called_once_with()
        run_session.assert_called_once_with()

    def test_action_toggle_previous_screen_notifies_when_unsupported(self):
        app = GitNightCommanderApp()

        with (
            patch.object(app, "suspend", side_effect=SuspendNotSupported),
            patch.object(app, "notify") as notify,
        ):
            app.action_toggle_previous_screen()

        notify.assert_called_once_with("Previous-screen toggle is not supported in this terminal")

    def test_status_header_is_composed_after_status_list(self):
        import inspect

        source = inspect.getsource(GitNightCommanderApp.compose)
        status_list_index = source.find('yield StatusList(id="status_list")')
        status_header_index = source.find('yield Label("", id="status-header")')

        self.assertNotEqual(status_list_index, -1)
        self.assertNotEqual(status_header_index, -1)
        self.assertLess(status_list_index, status_header_index)

    def test_app_defaults_to_midnight_commander_theme(self):
        app = GitNightCommanderApp()

        self.assertEqual(app.theme, MIDNIGHT_COMMANDER_THEME_NAME)

    def test_register_app_themes_registers_midnight_commander(self):
        app = GitNightCommanderApp()

        with patch.object(app, "register_theme") as register_theme:
            app._register_app_themes()

        registered_names = {
            call.args[0].name for call in register_theme.call_args_list if call.args
        }
        self.assertIn(MIDNIGHT_COMMANDER_THEME.name, registered_names)

    def test_on_mount_restores_saved_theme(self):
        app = GitNightCommanderApp()

        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text(json.dumps({"theme": "nord"}), encoding="utf-8")

            with (
                patch.object(app, "_settings_path", return_value=settings_path),
                patch.object(app, "_load_status") as load_status,
                patch.object(app, "_load_commits") as load_commits,
            ):
                app.on_mount()

        self.assertEqual(app.theme, "nord")
        load_status.assert_called_once_with()
        load_commits.assert_called_once_with()

    def test_action_set_theme_persists_theme_setting(self):
        app = _mock_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"

            with (
                patch.object(app, "_settings_path", return_value=settings_path),
                patch.object(app, "notify") as notify,
            ):
                app.action_set_theme(MIDNIGHT_COMMANDER_THEME_NAME)

            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                {"theme": MIDNIGHT_COMMANDER_THEME_NAME},
            )

        self.assertEqual(app.theme, MIDNIGHT_COMMANDER_THEME_NAME)
        notify.assert_called_once_with(f"Theme: {MIDNIGHT_COMMANDER_THEME_NAME}")

    def test_short_file_list_header_includes_status_column(self):
        app = GitNightCommanderApp()
        app.file_list_mode = MODE_SHORT

        header = app._column_header_text()

        self.assertTrue(header.startswith(f"{'Status':<{STATUS_WIDTH}}"))
        self.assertLess(header.index("Status"), header.index("Name"))
        self.assertTrue(header.endswith(f"{'Size':>{SIZE_WIDTH}}  {'Modify time':>{MTIME_WIDTH}}"))

    def test_long_file_list_header_includes_status_column(self):
        app = GitNightCommanderApp()
        app.file_list_mode = MODE_LONG

        header = app._column_header_text()

        self.assertTrue(header.startswith(f"{'Status':<{STATUS_WIDTH}}"))
        self.assertLess(header.index("Status"), header.index("Name"))
        self.assertTrue(header.endswith(f"{'Size':>{SIZE_WIDTH}}  {'Modify time':>{MTIME_WIDTH}}"))

    def test_load_status_expands_name_column_to_fill_status_list_width(self):
        app = _mock_app()
        app.file_list_mode = MODE_LONG

        filelist = MagicMock(spec=GitFilelist)
        filelist.status_message.return_value = "1 file(s) changed"
        filelist.row_texts.return_value = []
        app.git.load_status.return_value = filelist

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.content_region = types.SimpleNamespace(width=118)
        inline_diff = MagicMock()
        diff_full = MagicMock()
        switcher = MagicMock()
        column_header = MagicMock()
        status_header = MagicMock()

        def query_one(selector, *args, **kwargs):
            if selector == "#status-view":
                return status_view
            if selector == "#status_list":
                return status_list
            if selector == "#file-diff":
                return inline_diff
            if selector == "#diff-full":
                return diff_full
            if selector == "#column-header":
                return column_header
            if selector == "#status-header":
                return status_header
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one

        app._load_status()

        self.assertEqual(app._name_width(), 78)
        column_header.update.assert_called_once_with(app._column_header_text(78))
        filelist.row_texts.assert_called_once()
        call = filelist.row_texts.call_args
        self.assertEqual(call.args, (app.repo_path,))
        self.assertEqual(call.kwargs["status_width"], STATUS_WIDTH)
        self.assertEqual(call.kwargs["name_width"], 78)
        self.assertEqual(call.kwargs["size_width"], SIZE_WIDTH)
        self.assertEqual(call.kwargs["mtime_width"], MTIME_WIDTH)

    def test_git_reads_are_scheduled_on_thread_workers(self):
        """Every git read that grows with repo size must go through a thread
        worker — running one inline would stall Textual's event loop and
        freeze input until the subprocess returned."""
        app = _mock_app()
        scheduled: list[dict[str, object]] = []
        app.run_worker = lambda work, **kwargs: scheduled.append(kwargs)

        app._load_status()
        app._load_commits()
        app._load_commit_detail("cafe123")
        app._render_entry_into("file-diff", GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py"))

        self.assertEqual(len(scheduled), 4)
        self.assertTrue(all(kwargs["thread"] for kwargs in scheduled))
        # Nothing ran on the calling (UI) thread.
        app.git.load_status.assert_not_called()
        app.git.submodule_branch_mismatches.assert_not_called()
        app.git.load_commits.assert_not_called()
        app.git.show_commit.assert_not_called()
        app.git.load_file_diff.assert_not_called()

    def test_refresh_status_layout_reflows_columns_without_reloading_git(self):
        """Terminal resize must re-flow the Size / Modify time columns flush
        to the right edge without re-running git status."""
        app = _mock_app()
        app.file_list_mode = MODE_LONG

        filelist = MagicMock(spec=GitFilelist)
        filelist.status_message.return_value = "1 file(s) changed"
        filelist.row_texts.return_value = []
        filelist.entry_at.return_value = None
        app.status_filelist = filelist

        status_list = MagicMock()
        status_list.index = None
        status_list.content_region = types.SimpleNamespace(width=160)
        column_header = MagicMock()

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            if selector == "#column-header":
                return column_header
            return MagicMock()

        app.query_one.side_effect = query_one

        app._refresh_status_layout()

        self.assertEqual(app._name_width(), 120)
        column_header.update.assert_called_once_with(app._column_header_text(120))
        filelist.row_texts.assert_called_once()
        call = filelist.row_texts.call_args
        self.assertEqual(call.args, (app.repo_path,))
        self.assertEqual(call.kwargs["status_width"], STATUS_WIDTH)
        self.assertEqual(call.kwargs["name_width"], 120)
        self.assertEqual(call.kwargs["size_width"], SIZE_WIDTH)
        self.assertEqual(call.kwargs["mtime_width"], MTIME_WIDTH)
        app.git.load_status.assert_not_called()
        app.git.submodule_branch_mismatches.assert_not_called()


EXPECTED_SHORTCUTS: list[tuple[str, str, str]] = [
    ("f10", "quit", "Quit"),
    ("f5", "refresh", "Refresh"),
    ("ctrl+o", "toggle_previous_screen", "Prev Screen"),
    ("f3", "toggle_file_list", "Short/long list"),
    ("s", "stage_file", "Stage"),
    ("u", "unstage_file", "Unstage"),
    ("f7", "restore_file", "Restore"),
    ("f8", "delete_file", "Delete"),
    ("c", "commit_files", "Commit"),
    ("p", "pull", "Pull"),
    ("P", "push", "Push"),
    ("z", "stash", "Stash"),
    ("Z", "stash_pop", "Stash pop"),
    ("ctrl+u", "clear_selection", "Clear selection"),
    ("f9", "open_menu", "Menu"),
    ("f1", "keys", "Keys"),
    ("escape", "escape", "Back / close"),
]


def _key_event(key: str, character: str | None = None) -> Any:
    """A stand-in for textual.events.Key, for driving a dialog's on_key."""
    event = MagicMock()
    event.key = key
    event.character = character
    return event


def _mock_app() -> Any:
    """Build a GitNightCommanderApp with DOM / git access stubbed out for action tests.

    Returns ``Any`` so call sites can freely reassign methods/attrs to
    ``MagicMock`` and access mock-specific attributes (``return_value``,
    ``side_effect``, ``assert_*``) without fighting pyright.
    """
    app = GitNightCommanderApp()
    app.query_one = MagicMock(return_value=MagicMock())
    app.query = MagicMock(return_value=[])
    # The git reads run on Textual thread workers (`@work(thread=True)`), which
    # need a running event loop to schedule. Collapsing run_worker and
    # call_from_thread to a direct call runs the worker body and its UI
    # callback inline, so tests keep their synchronous call/assert shape.
    app.run_worker = MagicMock(side_effect=lambda work, **kwargs: work())
    app.call_from_thread = MagicMock(
        side_effect=lambda callback, *args, **kwargs: callback(*args, **kwargs)
    )
    app.git = MagicMock()
    app.git.load_status.return_value = GitFilelist()
    app.git.load_commits.return_value = []
    # Route entry-aware methods through the legacy filename-keyed mocks so
    # assertions on stage_file / unstage_file / stage_command / commit / etc.
    # keep working without per-test rewires. Submodule-specific behaviour is
    # exercised via tests that override these directly.
    app.git.stage_entry.side_effect = lambda e: app.git.stage_file(e.filename)
    app.git.unstage_entry.side_effect = lambda e: app.git.unstage_file(e.filename)
    app.git.stage_command_for.side_effect = lambda e: app.git.stage_command(e.filename)
    app.git.unstage_command_for.side_effect = lambda e: app.git.unstage_command(e.filename)
    app.git.commit_with_selection.side_effect = lambda _t, msg: app.git.commit(msg)
    # Real `commit_with_selection_commands` walks submodules; the parent-only
    # shape is a single `git commit`, which is what the commit confirmation
    # lists for the entries these tests use.
    app.git.commit_with_selection_commands.side_effect = lambda _t, msg: [
        ["git", "commit", "-m", msg]
    ]
    app.git.entry_command_filename.side_effect = lambda e: e.filename
    # Dialogs are ModalScreens now, so every one of them arrives through
    # push_screen. Capturing it lets tests inspect the screen that was pushed
    # and drive its dismiss callback without a live Textual app.
    app.push_screen = MagicMock()
    return app


class _DialogProbe:
    """Observes the dialogs an app opened, and closes them.

    Dialogs are ModalScreens, so the seam a test watches is `app.push_screen`
    rather than a widget's show()/hide(). `confirm()` / `cancel()` stand in
    for the user pressing Y / N, invoking the callback the app registered.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    @property
    def pushed(self) -> list[Any]:
        return [call.args[0] for call in self._app.push_screen.call_args_list]

    def assert_not_shown(self) -> None:
        assert not self.pushed, f"expected no dialog, got {self.pushed}"

    def assert_open(self) -> Any:
        pushed = self.pushed
        assert len(pushed) == 1, f"expected exactly one dialog, got {pushed}"
        return pushed[0]

    def assert_confirm(self, prompt: str, commands: list[str]) -> None:
        screen = self.assert_open()
        assert (screen.prompt, screen.commands) == (prompt, commands), (
            f"expected {(prompt, commands)}, got {(screen.prompt, screen.commands)}"
        )

    def commands(self, index: int = -1) -> list[str]:
        return self.pushed[index].commands

    def prompt(self, index: int = -1) -> str:
        return self.pushed[index].prompt

    def _resolve(self, result: Any, index: int = -1) -> None:
        self._app.push_screen.call_args_list[index].kwargs["callback"](result)

    def confirm(self, index: int = -1) -> None:
        """The user pressed Y."""
        self._resolve(True, index)

    def cancel(self, index: int = -1) -> None:
        """The user pressed N / Esc."""
        self._resolve(False, index)

    def reset(self) -> None:
        self._app.push_screen.reset_mock()


def _pushed_screen(app: Any, index: int = -1) -> Any:
    """The screen object handed to the `index`-th push_screen call."""
    return app.push_screen.call_args_list[index].args[0]


def _pushed_callback(app: Any, index: int = -1) -> Any:
    """The dismiss callback registered by the `index`-th push_screen call."""
    return app.push_screen.call_args_list[index].kwargs["callback"]


def _dismiss(app: Any, result: Any, index: int = -1) -> None:
    """Simulate the user closing the pushed dialog with `result`."""
    _pushed_callback(app, index)(result)


class TestKeyboardShortcutsTable(unittest.TestCase):
    """Tests over the SHORTCUTS data structure / BINDINGS derived from it."""

    def test_expected_shortcuts_are_all_registered(self):
        keys_by_action: dict[str | None, list[str | None]] = {}
        for binding in GitNightCommanderApp.BINDINGS:
            keys_by_action.setdefault(getattr(binding, "action", None), []).append(
                getattr(binding, "key", None)
            )
        for key, action, _desc in EXPECTED_SHORTCUTS:
            with self.subTest(action=action):
                self.assertIn(action, keys_by_action)
                # The primary key comes first; aliases follow it.
                self.assertEqual(keys_by_action[action][0], key)

    def test_file_list_toggle_bound_to_f3(self):
        matches = [
            b
            for b in GitNightCommanderApp.BINDINGS
            if getattr(b, "action", None) == "toggle_file_list"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(getattr(matches[0], "key", None), "f3")

    def test_flow_control_and_werase_keys_are_not_bound(self):
        """Ctrl+S is XOFF and Ctrl+W is werase in the shell spawned by Ctrl+O,
        so neither may be an app-level shortcut."""
        keys = [getattr(b, "key", None) for b in GitNightCommanderApp.BINDINGS]
        self.assertNotIn("ctrl+s", keys)
        self.assertNotIn("ctrl+w", keys)

    def test_commit_message_submit_bound_to_f2(self):
        matches = [
            b for b in CommitTextArea.BINDINGS if getattr(b, "action", None) == "commit_submit"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(getattr(matches[0], "key", None), "f2")

    def test_file_list_modes_have_no_direct_key_bindings(self):
        """Both modes stay reachable from the File menu, but the keyboard
        offers only the single F3 toggle."""
        actions = [getattr(b, "action", None) for b in GitNightCommanderApp.BINDINGS]
        self.assertNotIn("long_file_list", actions)
        self.assertNotIn("short_file_list", actions)
        self.assertNotIn("short_file_list_inline_diff", actions)
        self.assertNotIn("long_file_list_full_screen_diff", actions)

    def test_ctrl_q_is_not_bound(self):
        keys = [getattr(b, "key", None) for b in GitNightCommanderApp.BINDINGS]
        self.assertNotIn("ctrl+q", keys)

    def test_no_duplicate_shortcut_keys(self):
        keys = [getattr(b, "key", None) for b in GitNightCommanderApp.BINDINGS]
        self.assertEqual(len(keys), len(set(keys)), f"duplicate keys: {keys}")

    def test_every_binding_has_matching_action_method(self):
        for binding in GitNightCommanderApp.BINDINGS:
            action = getattr(binding, "action", None)
            with self.subTest(action=action):
                # `quit` is inherited from Textual's App base class.
                self.assertTrue(
                    action == "quit" or hasattr(GitNightCommanderApp, f"action_{action}"),
                    f"action_{action} is missing on GitNightCommanderApp",
                )

    def test_escape_binding_is_hidden_from_footer(self):
        escape = next(
            b for b in GitNightCommanderApp.BINDINGS if getattr(b, "action", None) == "escape"
        )
        self.assertFalse(getattr(escape, "show", True))

    def test_shortcuts_source_matches_bindings(self):
        """Editing SHORTCUTS / SHORTCUT_ALIASES is the one place you change a
        keybinding."""
        descriptions = {a: d for _, a, d, _ in SHORTCUTS}
        from_tables = [(k, a, d) for k, a, d, _ in SHORTCUTS] + [
            (k, a, descriptions[a]) for k, a in SHORTCUT_ALIASES
        ]
        from_bindings = [
            (getattr(b, "key", None), getattr(b, "action", None), getattr(b, "description", None))
            for b in GitNightCommanderApp.BINDINGS
        ]
        self.assertEqual(from_tables, from_bindings)

    def test_delete_is_reachable_by_f8_and_the_delete_key(self):
        """F8 is what every TUI file manager binds delete to; the Del key is
        the one desktop keyboards have and many laptops don't."""
        keys = [
            getattr(b, "key", None)
            for b in GitNightCommanderApp.BINDINGS
            if getattr(b, "action", None) == "delete_file"
        ]
        self.assertEqual(keys, ["f8", "delete"])

    def test_quit_is_reachable_by_f10_and_q(self):
        """F10 is the file-manager key for it, but it is not ours to rely on:
        a terminal can keep it (VS Code hands it to the debugger's Step Over
        and never forwards it), and a key the app never receives looks like
        an app ignoring it. A bare letter always arrives."""
        keys = [
            getattr(b, "key", None)
            for b in GitNightCommanderApp.BINDINGS
            if getattr(b, "action", None) == "quit"
        ]
        self.assertEqual(keys, ["f10", "q"])

    def test_only_f10_quits_from_inside_a_dialog(self):
        """Priority bindings are checked before the key reaches the modal, so
        a priority `q` would quit the app mid-commit-message."""
        priorities = {
            getattr(b, "key", None): getattr(b, "priority", False)
            for b in GitNightCommanderApp.BINDINGS
            if getattr(b, "action", None) == "quit"
        }
        self.assertTrue(priorities["f10"])
        self.assertFalse(priorities["q"])

    def test_alias_bindings_are_hidden_from_footer(self):
        """The footer keys off the binding, so a shown alias would list its
        action's description a second time."""
        aliases = {(k, a) for k, a in SHORTCUT_ALIASES}
        for binding in GitNightCommanderApp.BINDINGS:
            key, action = getattr(binding, "key", None), getattr(binding, "action", None)
            if (key, action) in aliases:
                with self.subTest(key=key):
                    self.assertFalse(getattr(binding, "show", True))

    def test_footer_shows_function_keys_upper_case(self):
        """Textual names function keys in lower case and shows that name
        verbatim; every other place in the app spells them `F8`."""
        displays = {
            getattr(b, "key", None): getattr(b, "key_display", None)
            for b in GitNightCommanderApp.BINDINGS
        }
        self.assertEqual(displays["f10"], "F10")
        self.assertEqual(displays["f8"], "F8")

    def test_footer_leaves_non_function_keys_to_textual(self):
        """`^o` reads better than a spelled-out modifier, so only the function
        keys carry an override."""
        displays = {
            getattr(b, "key", None): getattr(b, "key_display", None)
            for b in GitNightCommanderApp.BINDINGS
        }
        self.assertIsNone(displays["ctrl+o"])
        self.assertIsNone(displays["s"])

    def test_menu_hint_shows_the_primary_key_not_the_alias(self):
        self.assertEqual(MENU_HINTS_BY_ACTION["delete_file"], "F8")

    def test_help_dialog_lists_every_key_for_an_action(self):
        row = next(r for r in HELP_SHORTCUTS if r[1] == "delete_file")
        self.assertEqual(row, ("F8, delete", "delete_file", "Delete", True))

    def test_repo_commands_are_letter_pairs_with_shift_as_the_counterpart(self):
        """The git verbs are letters (s / u / c); the repo commands follow
        the same rule, with shift meaning the other half of the pair."""
        keys = {a: k for k, a, _, _ in SHORTCUTS}
        self.assertEqual((keys["pull"], keys["push"]), ("p", "P"))
        self.assertEqual((keys["stash"], keys["stash_pop"]), ("z", "Z"))

    def test_repo_commands_stay_out_of_the_footer(self):
        """Eleven shown bindings already run past 80 columns; the Repo menu
        and Help -> Keys are where these four are advertised."""
        shown = {a for _, a, _, show in SHORTCUTS if show}
        for action in ("pull", "push", "stash", "stash_pop"):
            with self.subTest(action=action):
                self.assertNotIn(action, shown)

    def test_help_is_reachable_with_f1(self):
        keys = {a: k for k, a, _, _ in SHORTCUTS}
        self.assertEqual(keys["keys"], "f1")

    def test_commit_is_reachable_by_c_and_f2(self):
        """F2 submits the message inside the dialog, so the same key opens
        the flow and closes it."""
        keys = [
            getattr(b, "key", None)
            for b in GitNightCommanderApp.BINDINGS
            if getattr(b, "action", None) == "commit_files"
        ]
        self.assertEqual(keys, ["c", "f2"])

    def test_shifted_letters_are_spelled_out_rather_than_shown_bare(self):
        """Textual names shift+P `P`, one cell from `p` — the two halves of a
        pair have to be told apart in the footer and the hint column."""
        displays = {
            getattr(b, "key", None): getattr(b, "key_display", None)
            for b in GitNightCommanderApp.BINDINGS
        }
        self.assertEqual(displays["P"], "Shift+P")
        self.assertEqual(displays["Z"], "Shift+Z")
        self.assertEqual(MENU_HINTS_BY_ACTION["push"], "Shift+P")
        self.assertEqual(MENU_HINTS_BY_ACTION["pull"], "P")
        self.assertEqual(
            next(r for r in HELP_SHORTCUTS if r[1] == "stash_pop")[0],
            "Shift+Z",
        )


class TestKeyboardShortcutActions(unittest.TestCase):
    """Invoke each action method and assert its observable state change."""

    def _status_mode_query_one(
        self,
        *,
        status_view,
        status_list,
        inline_diff,
        diff_full,
        switcher,
        column_header=None,
        status_header=None,
    ):
        if column_header is None:
            column_header = MagicMock()
        if status_header is None:
            status_header = MagicMock()

        def query_one(selector, *args, **kwargs):
            if selector == "#status-view":
                return status_view
            if selector == "#status_list":
                return status_list
            if selector == "#file-diff":
                return inline_diff
            if selector == "#diff-full":
                return diff_full
            if selector == "#column-header":
                return column_header
            if selector == "#status-header":
                return status_header
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        return query_one

    def test_action_short_file_list_sets_short_mode(self):
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        app.action_short_file_list()
        self.assertEqual(app.file_list_mode, MODE_SHORT)

    def test_action_short_file_list_preserves_highlighted_file(self):
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        app.git.load_status.return_value = GitFilelist([first, second])

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 1
        inline_diff = MagicMock()
        diff_full = MagicMock()
        switcher = MagicMock()
        switcher.current = "status-view"
        app.query_one.side_effect = self._status_mode_query_one(
            status_view=status_view,
            status_list=status_list,
            inline_diff=inline_diff,
            diff_full=diff_full,
            switcher=switcher,
        )

        app.action_short_file_list()

        self.assertEqual(app.file_list_mode, MODE_SHORT)
        self.assertEqual(status_list.index, 1)

    def test_action_long_file_list_sets_long_mode(self):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.action_long_file_list()
        self.assertEqual(app.file_list_mode, MODE_LONG)

    def test_mode_switch_defers_highlight_restore_past_listview_prune(self):
        """Switching short↔long calls ListView.clear() + append(), but Textual
        processes prune asynchronously so the cleared rows stay in _nodes.
        Restoring the selection synchronously would highlight a dying old
        item. The restore must be scheduled via call_after_refresh so it
        runs after the DOM settles."""
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        app.git.load_status.return_value = GitFilelist([first, second])

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 1
        inline_diff = MagicMock()
        diff_full = MagicMock()
        switcher = MagicMock()
        switcher.current = "status-view"
        app.query_one.side_effect = self._status_mode_query_one(
            status_view=status_view,
            status_list=status_list,
            inline_diff=inline_diff,
            diff_full=diff_full,
            switcher=switcher,
        )
        with patch.object(app, "call_after_refresh") as scheduled:
            app.action_short_file_list()

        scheduled.assert_called_once_with(app._restore_status_selection, second)

    def test_action_long_file_list_preserves_highlighted_file(self):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        app.git.load_status.return_value = GitFilelist([first, second])

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 1
        inline_diff = MagicMock()
        diff_full = MagicMock()
        switcher = MagicMock()
        switcher.current = "status-view"
        app.query_one.side_effect = self._status_mode_query_one(
            status_view=status_view,
            status_list=status_list,
            inline_diff=inline_diff,
            diff_full=diff_full,
            switcher=switcher,
        )

        app.action_long_file_list()

        self.assertEqual(app.file_list_mode, MODE_LONG)
        self.assertEqual(status_list.index, 1)

    def test_status_list_highlight_updates_git_filelist(self):
        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        event = MagicMock()
        event.list_view.id = "status_list"
        event.list_view.index = 1

        app.on_list_view_highlighted(event)

        self.assertEqual(app.status_entries.highlighted_entry, second)

    def test_status_list_highlight_shows_long_status_in_bottom_line(self):
        """Highlighting a file appends its long-format git status description
        (e.g. "modified (staged)") to the bottom status line, separated from the
        "N file(s) changed" text."""
        app = _mock_app()
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/thing.py")
        app.status_entries = GitFilelist([entry])
        status_header = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_header if sel == "#status-header" else MagicMock()
        )
        event = MagicMock()
        event.list_view.id = "status_list"
        event.list_view.index = 0

        app.on_list_view_highlighted(event)

        status_header.update.assert_called_once_with("1 file(s) changed | modified (not staged)")

    def test_status_list_no_highlight_shows_only_file_count(self):
        """With nothing highlighted the bottom status line is just the count."""
        app = _mock_app()
        app.status_entries = GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")])
        status_header = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_header if sel == "#status-header" else MagicMock()
        )

        app._update_status_header()

        status_header.update.assert_called_once_with("1 file(s) changed")

    def test_restore_status_selection_updates_git_filelist_highlight(self):
        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])

        status_list = MagicMock()
        app.query_one.side_effect = lambda selector, *args, **kwargs: (
            status_list if selector == "#status_list" else MagicMock()
        )

        app._restore_status_selection(second)

        self.assertEqual(app.status_entries.highlighted_entry, second)
        self.assertEqual(status_list.index, 1)

    def test_toggle_file_list_from_short_switches_to_long(self):
        """The toggle routes to the full-screen-diff variant so a focused
        inline diff follows the user into long mode."""
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        with (
            patch.object(app, "action_long_file_list_full_screen_diff") as to_long,
            patch.object(app, "action_short_file_list_inline_diff") as to_short,
        ):
            app.action_toggle_file_list()
        to_long.assert_called_once_with()
        to_short.assert_not_called()

    def test_toggle_file_list_from_long_switches_to_short(self):
        """The toggle routes to the inline-diff variant so an open full-screen
        diff follows the user back into short mode."""
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        with (
            patch.object(app, "action_long_file_list_full_screen_diff") as to_long,
            patch.object(app, "action_short_file_list_inline_diff") as to_short,
        ):
            app.action_toggle_file_list()
        to_short.assert_called_once_with()
        to_long.assert_not_called()

    def test_action_long_file_list_adds_long_mode_css_class(self):
        app = _mock_app()
        status_view = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_view if sel == "#status-view" else MagicMock()
        )
        app.action_long_file_list()
        status_view.add_class.assert_called_with("long-mode")

    def test_action_short_file_list_removes_long_mode_css_class(self):
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        status_view = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_view if sel == "#status-view" else MagicMock()
        )
        app.action_short_file_list()
        status_view.remove_class.assert_called_with("long-mode")

    def test_action_short_file_list_after_long_exits_diff_view(self):
        """Regression: switching to long mode then opening a file lands on
        diff-view; switching back must still return to status-view (this is the
        user-reported bug)."""
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        switcher = MagicMock()
        switcher.current = "diff-view"
        status_view = MagicMock()

        def query_one(selector, *args, **kwargs):
            if selector == "#status-view":
                return status_view
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one
        app.action_short_file_list()
        self.assertEqual(app.file_list_mode, MODE_SHORT)
        self.assertEqual(switcher.current, "status-view")

    def test_action_view_status_switches_to_status_view(self):
        app = _mock_app()
        switcher = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            switcher if isinstance(sel, type) else MagicMock()
        )
        app.action_view_status()
        self.assertEqual(switcher.current, "status-view")

    def test_action_view_history_switches_to_history_view(self):
        app = _mock_app()
        switcher = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            switcher if isinstance(sel, type) else MagicMock()
        )
        app.action_view_history()
        self.assertEqual(switcher.current, "history-view")

    def test_action_open_menu_opens_first_menu(self):
        app = _mock_app()
        with patch.object(app, "_show_menu_by_index") as show:
            app.action_open_menu()
        show.assert_called_once_with(0)

    def test_action_refresh_in_status_view_reloads_status(self):
        app = _mock_app()
        switcher = MagicMock()
        switcher.current = "status-view"
        app.query_one.side_effect = lambda sel, *a, **k: (
            switcher if isinstance(sel, type) else MagicMock()
        )
        with (
            patch.object(app, "_load_status") as load_status,
            patch.object(app, "_load_commits") as load_commits,
        ):
            app.action_refresh()
        load_status.assert_called_once()
        load_commits.assert_not_called()

    def test_action_refresh_in_history_view_reloads_commits(self):
        app = _mock_app()
        switcher = MagicMock()
        switcher.current = "history-view"
        app.query_one.side_effect = lambda sel, *a, **k: (
            switcher if isinstance(sel, type) else MagicMock()
        )
        with (
            patch.object(app, "_load_status") as load_status,
            patch.object(app, "_load_commits") as load_commits,
        ):
            app.action_refresh()
        load_commits.assert_called_once()
        load_status.assert_not_called()

    def test_action_escape_in_diff_view_returns_to_status_view(self):
        app = _mock_app()
        switcher = MagicMock()
        switcher.current = "diff-view"
        app.query_one.side_effect = lambda sel, *a, **k: (
            switcher if isinstance(sel, type) else MagicMock()
        )
        app.action_escape()
        self.assertEqual(switcher.current, "status-view")

    def test_action_escape_in_diff_view_restores_last_status_selection(self):
        app = _mock_app()
        other = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/other.py")
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")
        app.status_entries = GitFilelist([other, entry])
        app._last_status_entry = entry

        status_list = MagicMock()
        status_list.index = None
        diff_full = MagicMock()
        switcher = MagicMock()
        switcher.current = "diff-view"

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            if selector == "#diff-full":
                return diff_full
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one

        app.action_escape()

        self.assertEqual(switcher.current, "status-view")
        self.assertEqual(status_list.index, 1)
        status_list.focus.assert_called_once_with()

    def test_action_escape_in_diff_view_reapplies_highlight_when_index_is_unchanged(self):
        app = _mock_app()
        other = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/other.py")
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")
        app.status_entries = GitFilelist([other, entry])
        app._last_status_entry = entry

        status_list = MagicMock()
        status_list.index = 1
        diff_full = MagicMock()
        switcher = MagicMock()
        switcher.current = "diff-view"

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            if selector == "#diff-full":
                return diff_full
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one

        app.action_escape()

        self.assertEqual(switcher.current, "status-view")
        self.assertEqual(status_list.index, 1)
        status_list.watch_index.assert_called_once_with(1, 1)
        status_list.focus.assert_called_once_with()

    def test_f3_with_focused_inline_diff_preserves_diff_full_screen(self):
        """F3 while the inline diff is the focused widget must carry the diff
        into the full-screen diff view instead of closing it."""
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        other = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/other.py")
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")
        app.status_entries = GitFilelist([other, entry])
        app.git.load_status.return_value = GitFilelist([other, entry])
        app.git.load_file_diff.return_value = "diff text"

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 1
        inline_diff = MagicMock()
        inline_diff.display = True
        diff_full = MagicMock()
        switcher = MagicMock()
        app.query_one.side_effect = self._status_mode_query_one(
            status_view=status_view,
            status_list=status_list,
            inline_diff=inline_diff,
            diff_full=diff_full,
            switcher=switcher,
        )
        with patch.object(
            type(app), "focused", new_callable=PropertyMock, return_value=inline_diff
        ):
            app.action_long_file_list_full_screen_diff()

        self.assertEqual(app.file_list_mode, MODE_LONG)
        self.assertEqual(switcher.current, "diff-view")
        self.assertEqual(status_list.index, 1)
        diff_full.show.assert_called_with("diff text", "pkg/thing.py")

    def test_f3_from_focused_file_list_switches_mode_instead_of_expanding_diff(self):
        """Regression: Enter leaves the inline diff on screen, so a visible
        diff alone must not turn F3 into "expand this diff" — with the focus
        back on the file list, F3 is the mode switch it advertises."""
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")
        app.status_entries = GitFilelist([entry])
        app.git.load_status.return_value = GitFilelist([entry])

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 0
        inline_diff = MagicMock()
        inline_diff.display = True
        diff_full = MagicMock()
        switcher = MagicMock()
        app.query_one.side_effect = self._status_mode_query_one(
            status_view=status_view,
            status_list=status_list,
            inline_diff=inline_diff,
            diff_full=diff_full,
            switcher=switcher,
        )
        with patch.object(
            type(app), "focused", new_callable=PropertyMock, return_value=status_list
        ):
            app.action_long_file_list_full_screen_diff()

        self.assertEqual(app.file_list_mode, MODE_LONG)
        status_view.add_class.assert_called_with("long-mode")
        self.assertNotEqual(switcher.current, "diff-view")
        diff_full.show.assert_not_called()
        self.assertFalse(inline_diff.display)

    def test_f3_without_open_diff_keeps_old_behavior(self):
        """F3 with no diff visible must still switch mode the old way
        (leave diff view, no show() on diff-full)."""
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        inline_diff = MagicMock()
        inline_diff.display = False
        diff_full = MagicMock()

        def query_one(selector, *args, **kwargs):
            if selector == "#file-diff":
                return inline_diff
            if selector == "#diff-full":
                return diff_full
            return MagicMock()

        app.query_one.side_effect = query_one
        app.action_long_file_list_full_screen_diff()

        self.assertEqual(app.file_list_mode, MODE_LONG)
        diff_full.show.assert_not_called()

    def test_long_file_list_menu_entry_never_expands_a_diff(self):
        """The File menu entries are direct mode sets: they must not depend on
        what is open or focused (and by the time one runs, closing the menu has
        already handed focus back to the active view)."""
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")
        app.status_entries = GitFilelist([entry])
        app.git.load_status.return_value = GitFilelist([entry])

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 0
        inline_diff = MagicMock()
        inline_diff.display = True
        diff_full = MagicMock()
        switcher = MagicMock()
        app.query_one.side_effect = self._status_mode_query_one(
            status_view=status_view,
            status_list=status_list,
            inline_diff=inline_diff,
            diff_full=diff_full,
            switcher=switcher,
        )
        with patch.object(
            type(app), "focused", new_callable=PropertyMock, return_value=inline_diff
        ):
            app.action_long_file_list()

        self.assertEqual(app.file_list_mode, MODE_LONG)
        diff_full.show.assert_not_called()

    def test_ctrl_s_with_full_screen_diff_preserves_diff_inline(self):
        """Ctrl+S while the full-screen diff is open in long mode must move
        the diff back to the inline panel in short mode."""
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        other = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/other.py")
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")
        app.status_entries = GitFilelist([other, entry])
        app.git.load_status.return_value = GitFilelist([other, entry])
        app.git.load_file_diff.return_value = "diff text"

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 1
        inline_diff = MagicMock()
        diff_full = MagicMock()
        switcher = MagicMock()
        switcher.current = "diff-view"
        app.query_one.side_effect = self._status_mode_query_one(
            status_view=status_view,
            status_list=status_list,
            inline_diff=inline_diff,
            diff_full=diff_full,
            switcher=switcher,
        )
        app.action_short_file_list_inline_diff()

        self.assertEqual(app.file_list_mode, MODE_SHORT)
        self.assertEqual(switcher.current, "status-view")
        self.assertEqual(status_list.index, 1)
        inline_diff.show.assert_called_with("diff text", "pkg/thing.py")

    def test_ctrl_s_without_open_diff_just_switches_mode(self):
        """Ctrl+S when the full-screen diff is not visible falls through to
        plain short-mode switching."""
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        switcher = MagicMock()
        switcher.current = "status-view"
        inline_diff = MagicMock()

        def query_one(selector, *args, **kwargs):
            if selector == "#file-diff":
                return inline_diff
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one
        app.action_short_file_list_inline_diff()

        self.assertEqual(app.file_list_mode, MODE_SHORT)
        inline_diff.show.assert_not_called()

    def test_action_escape_closes_open_dropdown(self):
        app = _mock_app()
        dropdown = MagicMock()
        dropdown.display = True
        label = MagicMock()
        switcher = MagicMock()
        switcher.current = "status-view"

        def query(cls):
            name = getattr(cls, "__name__", "")
            if name == "DropdownMenu":
                return [dropdown]
            if name == "MenuLabel":
                return [label]
            return []

        app.query.side_effect = query
        app.query_one.side_effect = lambda sel, *a, **k: (
            switcher if isinstance(sel, type) else MagicMock()
        )
        app.action_escape()
        dropdown.hide.assert_called_once()


def _diff_theme() -> MagicMock:
    """A theme whose diff/commit styles are all distinguishable strings."""
    theme = MagicMock()
    theme.diff_added_line = "green"
    theme.diff_added_line_number = "green dim"
    theme.diff_removed_line = "red"
    theme.diff_removed_line_number = "red dim"
    theme.diff_context_line_number = "dim"
    theme.commit_header_line = "bold"
    theme.diff_hunk_header = "cyan"
    return theme


@unittest.skipUnless(_TEXT_RECORDS_STYLES, "rich stub does not record styles")
class TestCommitDetailRendering(unittest.TestCase):
    """The commit pane renders `git show` output the way the file diff pane
    renders a diff: added text green, removed text red, no raw escape codes."""

    def _styled_runs(self, text) -> list[tuple[str, str]]:
        """(substring, style) for every styled run, in document order."""
        plain = text.plain
        return [(plain[span.start : span.end], span.style) for span in text.spans]

    def test_diffstat_graph_uses_the_diff_colors(self):
        detail = " gitnc/app.py | 18 +++++++++---------\n"

        runs = self._styled_runs(render_commit_detail(detail, theme=_diff_theme()))

        self.assertEqual(
            runs,
            [("+", "green")] * 9 + [("-", "red")] * 9,
        )

    def test_commit_header_block_is_styled_and_message_is_left_plain(self):
        detail = "commit cafe1234beef\nAuthor: A U Thor\nDate:   Mon Aug 10\n\n    subject\n"

        runs = self._styled_runs(render_commit_detail(detail, theme=_diff_theme()))

        self.assertEqual(
            runs,
            [
                ("commit cafe1234beef", "bold"),
                ("Author: A U Thor", "bold"),
                ("Date:   Mon Aug 10", "bold"),
            ],
        )

    def test_patch_body_gets_the_same_colors_as_the_file_diff_view(self):
        detail = "@@ -1,2 +1,2 @@\n context\n-gone\n+added\n"

        runs = self._styled_runs(render_commit_detail(detail, theme=_diff_theme()))

        self.assertEqual(
            runs,
            [("@@ -1,2 +1,2 @@", "cyan"), ("-gone", "red"), ("+added", "green")],
        )

    def test_per_file_headers_are_kept_and_styled(self):
        """Unlike FileDiff, which has one file and drops these, the commit pane
        needs them to show which file each hunk belongs to."""
        detail = "diff --git a/x.py b/x.py\nindex 111..222 100644\n--- a/x.py\n+++ b/x.py\n"

        text = render_commit_detail(detail, theme=_diff_theme())

        self.assertEqual(text.plain, detail.rstrip("\n"))
        self.assertEqual({style for _, style in self._styled_runs(text)}, {"bold"})

    def test_show_renders_through_the_active_theme(self):
        widget = MagicMock()
        widget.app._active_ui_theme.return_value = _diff_theme()

        CommitDetail.show(widget, "commit cafe1234beef\n")

        rendered = widget.update.call_args.args[0]
        self.assertEqual(rendered.plain, "commit cafe1234beef")
        self.assertEqual(self._styled_runs(rendered), [("commit cafe1234beef", "bold")])


class TestFileDiffFilenameHeader(unittest.TestCase):
    """The opened file's name must appear on the top line of the diff panel."""

    def test_on_list_view_selected_short_mode_passes_filename(self):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")])
        app.git.load_file_diff.return_value = "diff text"

        file_diff = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            file_diff if sel == "#file-diff" else MagicMock()
        )
        event = MagicMock()
        event.list_view.id = "status_list"
        event.list_view.index = 0

        app.on_list_view_selected(event)

        file_diff.show.assert_called_once_with("diff text", "pkg/thing.py")

    def test_on_list_view_selected_untracked_shows_file_content(self):
        """Pressing Enter on an untracked row must show the file content
        instead of the "Untracked file:" placeholder diff."""
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist([GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")])
        app.git.load_file_content.return_value = "line one\nline two\n"

        file_diff = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            file_diff if sel == "#file-diff" else MagicMock()
        )
        event = MagicMock()
        event.list_view.id = "status_list"
        event.list_view.index = 0

        app.on_list_view_selected(event)

        file_diff.show_content.assert_called_once_with("line one\nline two\n", "new.txt")
        file_diff.show.assert_not_called()

    def test_on_list_view_selected_long_mode_passes_filename_to_diff_full(self):
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        app.status_entries = GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/thing.py")])
        app.git.load_file_diff.return_value = "diff text"

        diff_full = MagicMock()
        switcher = MagicMock()

        def query_one(selector, *args, **kwargs):
            if selector == "#diff-full":
                return diff_full
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one
        event = MagicMock()
        event.list_view.id = "status_list"
        event.list_view.index = 0

        app.on_list_view_selected(event)

        self.assertEqual(switcher.current, "diff-view")
        diff_full.show.assert_called_once_with("diff text", "pkg/thing.py")

    def test_load_status_clears_stale_border_title(self):
        app = _mock_app()
        file_diff = MagicMock()
        file_diff.border_title = "leftover.py"
        app.query_one.side_effect = lambda sel, *a, **k: (
            file_diff if sel == "#file-diff" else MagicMock()
        )

        app._load_status()

        self.assertEqual(file_diff.border_title, "")

    def test_stale_diff_result_does_not_overwrite_a_newer_one(self):
        """A thread worker keeps running after `exclusive=True` cancels it, so
        arrowing off a slow file must not let its diff land on the next one."""
        app = _mock_app()
        file_diff = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            file_diff if sel == "#file-diff" else MagicMock()
        )
        slow = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/slow.py")
        fast = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/fast.py")

        app._render_entry_into("file-diff", slow)
        stale_serial = app._request_serials["diff"]
        app._render_entry_into("file-diff", fast)
        file_diff.show.reset_mock()
        app._apply_entry_diff(
            widget_id="file-diff", entry=slow, text="slow diff", serial=stale_serial
        )

        file_diff.show.assert_not_called()

    def test_stale_commit_detail_does_not_overwrite_a_newer_one(self):
        app = _mock_app()
        detail = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: detail if sel == "#detail" else MagicMock()

        app._load_commit_detail("cafe123")
        stale_serial = app._request_serials["commit-detail"]
        app._load_commit_detail("dead999")
        detail.show.reset_mock()
        app._apply_commit_detail(detail_text="detail we moved off", serial=stale_serial)

        detail.show.assert_not_called()

    def test_stale_status_result_does_not_overwrite_a_newer_one(self):
        """Two reloads in flight: the older `git status` must not repaint the
        list after the newer one already did."""
        app = _mock_app()
        app._load_status()
        stale_serial = app._request_serials["status"]
        app._load_status()
        status_list = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._apply_status(
            serial=stale_serial,
            filelist=GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "stale.py")]),
            previous_selections=set(),
            mismatches=[],
        )

        status_list.clear.assert_not_called()
        self.assertEqual(list(app.status_entries), [])

    def test_update_submodule_warnings_hides_label_when_no_mismatches(self):
        app = _mock_app()
        warnings_label = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            warnings_label if sel == "#submodule-warnings" else MagicMock()
        )
        app._submodule_mismatches = []

        app._update_submodule_warnings()

        warnings_label.update.assert_called_once_with("")
        warnings_label.add_class.assert_called_once_with("empty")

    def test_update_submodule_warnings_writes_one_line_per_mismatch(self):
        app = _mock_app()
        warnings_label = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            warnings_label if sel == "#submodule-warnings" else MagicMock()
        )
        app._submodule_mismatches = [
            ("vendor/lib_a", "dev", "main"),
            ("vendor/lib_b", None, "main"),
        ]

        app._update_submodule_warnings()

        warnings_label.remove_class.assert_called_once_with("empty")
        rendered = warnings_label.update.call_args.args[0]
        self.assertIn("vendor/lib_a", rendered)
        self.assertIn("'dev'", rendered)
        self.assertIn("'main'", rendered)
        self.assertIn("vendor/lib_b", rendered)
        self.assertIn("(detached HEAD)", rendered)
        self.assertEqual(rendered.count("\n"), 1)

    def test_update_submodule_warnings_uses_theme_warning_text_style(self):
        app = _mock_app()
        warnings_label = MagicMock()
        app.query_one.side_effect = lambda sel, *a, **k: (
            warnings_label if sel == "#submodule-warnings" else MagicMock()
        )
        app._submodule_mismatches = [("sub", "dev", "main")]
        ui_theme = MagicMock()
        ui_theme.warning_text = "bold red"
        with patch.object(app, "_active_ui_theme", return_value=ui_theme):
            app._update_submodule_warnings()

        rendered = warnings_label.update.call_args.args[0]
        self.assertTrue(rendered.startswith("[bold red]"))
        self.assertTrue(rendered.endswith("[/bold red]"))

    def test_leave_diff_view_clears_diff_full_border_title(self):
        app = _mock_app()
        diff_full = MagicMock()
        diff_full.border_title = "something.py"
        switcher = MagicMock()
        switcher.current = "diff-view"

        def query_one(selector, *args, **kwargs):
            if selector == "#diff-full":
                return diff_full
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one
        app._leave_diff_view()

        self.assertEqual(switcher.current, "status-view")
        self.assertEqual(diff_full.border_title, "")

    def test_file_diff_leaves_tab_to_textual_focus_cycling(self):
        """Tab is Textual's global "focus next" key; neither diff variant may
        claim it, or the standard focus cycle breaks.

        Called as an unbound method so we don't have to build a real Textual
        widget (which would require live DOM/App context)."""
        for widget_id in ("file-diff", "diff-full"):
            with self.subTest(widget_id=widget_id):
                fake = MagicMock()
                fake.id = widget_id
                event = MagicMock()
                event.key = "tab"

                FileDiff.on_key(fake, event)

                fake.app.query_one.assert_not_called()
                event.stop.assert_not_called()

    def test_status_list_focus_reapplies_current_highlight(self):
        """Focus arriving from anywhere — Tab back from the inline diff, a
        closing dialog — refreshes the highlight on the remembered row."""
        fake = MagicMock()
        fake.index = 1

        StatusList.on_focus(fake, MagicMock())

        fake.watch_index.assert_called_once_with(1, 1)

    def test_status_list_focus_with_no_highlight_is_a_no_op(self):
        """An empty list has index None; there is no row to re-highlight."""
        fake = MagicMock()
        fake.index = None

        StatusList.on_focus(fake, MagicMock())

        fake.watch_index.assert_not_called()

    def test_file_diff_show_signature_accepts_filename(self):
        """FileDiff.show takes (diff_text, filename) so the handler can
        pass the opened file's name through to the border_title. (Full
        end-to-end behavior is exercised by the handler tests above —
        direct invocation requires a live Textual app.)"""
        import inspect

        params = list(inspect.signature(FileDiff.show).parameters)
        self.assertEqual(params, ["self", "diff_text", "filename"])


class TestStageUnstageConfirmation(unittest.TestCase):
    """S stages the highlighted file; U unstages it. Both open a confirmation
    popup showing the exact git command; Y runs it, N / Esc cancels."""

    def _app_with_dialog(self, entries, highlight_index):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist(entries)
        app.git.load_status.return_value = GitFilelist(entries)
        app.git.stage_command.side_effect = lambda f: ["git", "add", "--", f]
        app.git.unstage_command.side_effect = lambda f: [
            "git",
            "restore",
            "--staged",
            "--",
            f,
        ]
        app.git.stage_file.return_value = MagicMock(returncode=0, stderr="")
        app.git.unstage_file.return_value = MagicMock(returncode=0, stderr="")

        dialog = _DialogProbe(app)
        status_list = MagicMock()
        status_list.index = highlight_index
        switcher = MagicMock()
        switcher.current = "status-view"

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one
        return app, dialog, status_list

    def test_stage_on_unstaged_file_shows_dialog_with_git_add_command(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)

        app.action_stage_file()

        dialog.assert_confirm("Stage pkg/a.py?", ["git add -- pkg/a.py"])
        app.git.stage_file.assert_not_called()

    def test_stage_on_staged_only_file_notifies_and_skips_dialog(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        with patch.object(app, "notify") as notify:
            app.action_stage_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("pkg/a.py has no unstaged changes")

    def test_unstage_on_staged_file_shows_dialog_with_restore_command(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)

        app.action_unstage_file()

        dialog.assert_confirm("Unstage pkg/a.py?", ["git restore --staged -- pkg/a.py"])
        app.git.unstage_file.assert_not_called()

    def test_unstage_on_unstaged_only_file_notifies_and_skips_dialog(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        with patch.object(app, "notify") as notify:
            app.action_unstage_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("pkg/a.py has no staged changes")

    def test_unstage_on_untracked_is_rejected(self):
        """Untracked files aren't staged, so U must be a no-op."""
        entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        with patch.object(app, "notify"):
            app.action_unstage_file()
        dialog.assert_not_shown()

    def test_stage_on_untracked_shows_dialog(self):
        """An untracked file can be staged (git add treats it as a new path)."""
        entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        app.action_stage_file()
        dialog.assert_confirm("Stage new.txt?", ["git add -- new.txt"])

    def test_stage_is_noop_without_highlight(self):
        app, dialog, _ = self._app_with_dialog(
            [GitEntry(GitCode.UNMODIFIED_MODIFIED, "a.py")], None
        )
        app.action_stage_file()
        dialog.assert_not_shown()

    def test_confirming_stage_runs_git_add_and_reloads(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, status_list = self._app_with_dialog([entry], 0)
        app.action_stage_file()

        with patch.object(app, "call_after_refresh", wraps=app.call_after_refresh) as after_refresh:
            dialog.confirm()

        app.git.stage_file.assert_called_once_with("pkg/a.py")
        app.git.load_status.assert_called_once_with()
        after_refresh.assert_called_once_with(app._restore_status_selection_and_focus, entry)
        self.assertEqual(status_list.index, 0)

    def test_confirming_stage_refocuses_only_after_deferred_selection_restore(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, status_list = self._app_with_dialog([entry], 0)
        app.action_stage_file()
        scheduled: list[tuple[Callable[..., None], tuple[object, ...], dict[str, object]]] = []

        def defer(callback: Callable[..., None], *args: object, **kwargs: object) -> None:
            scheduled.append((callback, args, kwargs))

        with (
            patch.object(app, "call_after_refresh", side_effect=defer),
            patch.object(app, "_focus_active_view") as focus_active_view,
        ):
            dialog.confirm()
            focus_active_view.assert_not_called()
            self.assertEqual(len(scheduled), 1)
            callback, args, kwargs = scheduled[0]
            callback(*args, **kwargs)

        self.assertEqual(status_list.index, 0)
        focus_active_view.assert_called_once_with()

    def test_confirming_unstage_runs_git_restore_staged(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        app.action_unstage_file()

        with patch.object(app, "_load_status"):
            dialog.confirm()

        app.git.unstage_file.assert_called_once_with("pkg/a.py")

    def test_cancelling_with_n_hides_dialog_without_running_command(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        app.action_stage_file()

        dialog.cancel()

        app.git.stage_file.assert_not_called()

    def test_cancelling_with_escape_hides_dialog_without_running_command(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        app.action_stage_file()

        dialog.cancel()

        app.git.stage_file.assert_not_called()

    def test_escape_key_cancels_the_dialog(self):
        """Esc is the dialog's own key now, not the app's: it dismisses with
        False so the app's callback runs the cancel branch."""
        dialog = ConfirmDialog(prompt="Stage pkg/a.py?", commands=["git add -- pkg/a.py"])
        with patch.object(ConfirmDialog, "dismiss") as dismiss:
            dialog.on_key(_key_event("escape"))

        dismiss.assert_called_once_with(False)

    def test_other_keys_are_swallowed_while_dialog_is_open(self):
        """An open dialog is modal: s/u/r must not leak through to their
        bindings (e.g. another 's' must not open a second dialog over the
        first). The dialog stops the event rather than dismissing."""
        dialog = ConfirmDialog(prompt="Stage pkg/a.py?", commands=["git add -- pkg/a.py"])
        event = _key_event("s")
        with patch.object(ConfirmDialog, "dismiss") as dismiss:
            dialog.on_key(event)

        dismiss.assert_not_called()
        event.stop.assert_called_once_with()
        event.prevent_default.assert_called_once_with()

    def test_dialog_is_a_modal_screen(self):
        """Modality is structural: Textual truncates the binding chain at the
        first modal (Screen._modal_binding_chain), so the app's own 's' / 'u'
        bindings cannot fire while this dialog is on the stack. That is what
        replaces the old `_pending_confirm` re-entrancy guards."""
        self.assertTrue(issubclass(ConfirmDialog, ModalScreen))

    def test_stage_failure_surfaces_stderr_in_notification(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry], 0)
        app.git.stage_file.return_value = MagicMock(returncode=1, stderr="pathspec did not match\n")
        app.action_stage_file()
        with patch.object(app, "_load_status"), patch.object(app, "notify") as notify:
            dialog.confirm()

        notify.assert_called_with("git add failed: pathspec did not match")


class TestBatchStageUnstageConfirmation(unittest.TestCase):
    """S / U with multi-selection batch the operation over selected files.

    The popup must show the exact `git` command per eligible file, must
    filter out files the action can't apply to (e.g. already-staged files
    when staging), and must be scrollable when the list is long."""

    def _app_with_dialog(self, entries, highlight_index=0):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist(entries)
        app.git.load_status.return_value = GitFilelist(entries)
        app.git.stage_command.side_effect = lambda f: ["git", "add", "--", f]
        app.git.unstage_command.side_effect = lambda f: [
            "git",
            "restore",
            "--staged",
            "--",
            f,
        ]
        app.git.stage_file.return_value = MagicMock(returncode=0, stderr="")
        app.git.unstage_file.return_value = MagicMock(returncode=0, stderr="")

        dialog = _DialogProbe(app)
        status_list = MagicMock()
        status_list.index = highlight_index
        switcher = MagicMock()
        switcher.current = "status-view"

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one
        return app, dialog, status_list

    def test_stage_multi_selection_shows_commands_for_all_eligible(self):
        a = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_stage_file()

        dialog.assert_confirm(
            "Stage 2 file(s)?",
            ["git add -- pkg/a.py", "git add -- pkg/b.py"],
        )
        app.git.stage_file.assert_not_called()

    def test_stage_multi_selection_filters_out_fully_staged_files(self):
        """Files with no unstaged changes (already staged, no new mods) must
        not appear in the dialog or be passed to `git add`."""
        staged_only = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/staged.py")
        unstaged = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/unstaged.py")
        app, dialog, _ = self._app_with_dialog([staged_only, unstaged])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_stage_file()

        dialog.assert_confirm("Stage 1 file(s)?", ["git add -- pkg/unstaged.py"])

    def test_stage_multi_selection_no_eligible_files_notifies(self):
        staged_only = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([staged_only])
        app.status_entries.toggle_selection(0)
        with patch.object(app, "notify") as notify:
            app.action_stage_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("No selected files have unstaged changes")

    def test_unstage_multi_selection_shows_commands_for_all_eligible(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_unstage_file()

        dialog.assert_confirm(
            "Unstage 2 file(s)?",
            [
                "git restore --staged -- pkg/a.py",
                "git restore --staged -- pkg/b.py",
            ],
        )
        app.git.unstage_file.assert_not_called()

    def test_unstage_multi_selection_filters_out_untracked_and_unstaged_only(self):
        untracked = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")
        unstaged = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/u.py")
        staged = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/s.py")
        app, dialog, _ = self._app_with_dialog([untracked, unstaged, staged])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.status_entries.toggle_selection(2)

        app.action_unstage_file()

        dialog.assert_confirm("Unstage 1 file(s)?", ["git restore --staged -- pkg/s.py"])

    def test_unstage_multi_selection_no_eligible_files_notifies(self):
        untracked = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")
        app, dialog, _ = self._app_with_dialog([untracked])
        app.status_entries.toggle_selection(0)
        with patch.object(app, "notify") as notify:
            app.action_unstage_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("No selected files have staged changes")

    def test_confirming_batch_stage_runs_git_add_for_each_eligible(self):
        staged_only = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/skip.py")
        a = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([staged_only, a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.status_entries.toggle_selection(2)
        app.action_stage_file()

        with patch.object(app, "_load_status"):
            dialog.confirm()

        self.assertEqual(
            [c.args for c in app.git.stage_file.call_args_list],
            [("pkg/a.py",), ("pkg/b.py",)],
        )

    def test_confirming_batch_unstage_runs_git_restore_for_each_eligible(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.action_unstage_file()

        with patch.object(app, "_load_status"):
            dialog.confirm()

        self.assertEqual(
            [c.args for c in app.git.unstage_file.call_args_list],
            [("pkg/a.py",), ("pkg/b.py",)],
        )

    def test_batch_stage_failure_surfaces_failed_filenames(self):
        a = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.git.stage_file.side_effect = [
            MagicMock(returncode=0, stderr=""),
            MagicMock(returncode=1, stderr="oops"),
        ]
        app.action_stage_file()

        with patch.object(app, "_load_status"), patch.object(app, "notify") as notify:
            dialog.confirm()

        notify.assert_called_with("git add failed for 1 file(s): pkg/b.py")

    def test_single_selection_only_still_uses_batch_flow(self):
        """One selected file still goes through the batch path — the user
        explicitly picked it via SPACE/CTRL+click, so the confirmation should
        match the multi-file format for consistency."""
        a = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        other = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([a, other], highlight_index=1)
        app.status_entries.toggle_selection(0)  # selects a.py, highlight on b.py

        app.action_stage_file()

        # Batch path: operates on the *selection* (a.py), not the highlight (b.py).
        dialog.assert_confirm("Stage 1 file(s)?", ["git add -- pkg/a.py"])

    def test_no_selection_falls_back_to_highlighted_file(self):
        """Without any selections, S/U operate on the highlighted file only."""
        a = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([a], highlight_index=0)

        app.action_stage_file()

        dialog.assert_confirm("Stage pkg/a.py?", ["git add -- pkg/a.py"])


class TestRestoreConfirmation(unittest.TestCase):
    """F7 restores file(s) to their HEAD state. Single-file fallback
    operates on the highlighted entry; multi-selection shows every command
    that will run. Ignored / unmerged entries are filtered out."""

    def _app_with_dialog(self, entries, highlight_index: int | None = 0):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist(entries)
        app.git.load_status.return_value = GitFilelist(entries)

        def restore_commands(entry):
            if entry.code.is_untracked:
                return [["git", "clean", "-f", "--", entry.filename]]
            if entry.code.staged.value == "A":
                return [
                    ["git", "restore", "--staged", "--", entry.filename],
                    ["git", "clean", "-f", "--", entry.filename],
                ]
            return [
                [
                    "git",
                    "restore",
                    "--source=HEAD",
                    "--staged",
                    "--worktree",
                    "--",
                    entry.filename,
                ]
            ]

        app.git.restore_commands.side_effect = restore_commands
        app.git.restore_file.return_value = [MagicMock(returncode=0, stderr="")]

        dialog = _DialogProbe(app)
        status_list = MagicMock()
        status_list.index = highlight_index

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            return MagicMock()

        app.query_one.side_effect = query_one
        return app, dialog, status_list

    def test_restore_on_modified_file_shows_restore_source_head_command(self):
        entry = GitEntry(GitCode.MODIFIED_MODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_restore_file()

        dialog.assert_confirm(
            "Restore pkg/a.py to HEAD?",
            [
                "git restore --source=HEAD --staged --worktree -- pkg/a.py",
            ],
        )
        app.git.restore_file.assert_not_called()

    def test_restore_on_untracked_file_shows_git_clean_only(self):
        entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "scratch.txt")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_restore_file()

        dialog.assert_confirm(
            "Restore scratch.txt to HEAD?",
            ["git clean -f -- scratch.txt"],
        )

    def test_restore_on_added_file_shows_two_commands_unstage_then_clean(self):
        """Added-in-index files aren't in HEAD, so the popup must show both
        the unstage and the clean step — the user needs to see that the
        file will be removed from disk, not just unstaged."""
        entry = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_restore_file()

        dialog.assert_confirm(
            "Restore pkg/new.py to HEAD?",
            [
                "git restore --staged -- pkg/new.py",
                "git clean -f -- pkg/new.py",
            ],
        )

    def test_restore_on_deleted_file_brings_it_back_with_restore_source_head(self):
        entry = GitEntry(GitCode.UNMODIFIED_DELETED, "pkg/gone.py")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_restore_file()

        dialog.assert_confirm(
            "Restore pkg/gone.py to HEAD?",
            ["git restore --source=HEAD --staged --worktree -- pkg/gone.py"],
        )

    def test_restore_on_ignored_file_notifies_and_skips_dialog(self):
        entry = GitEntry(GitCode.IGNORED_IGNORED, "build/out.log")
        app, dialog, _ = self._app_with_dialog([entry])
        with patch.object(app, "notify") as notify:
            app.action_restore_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("build/out.log cannot be restored")

    def test_restore_multi_selection_lists_every_command_for_every_file(self):
        """The popup must be an audit trail — every git invocation that will
        run, in order, one line each, so the user can veto before any of it
        happens."""
        modified = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/m.py")
        added = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        untracked = GitEntry(GitCode.UNTRACKED_UNTRACKED, "scratch.txt")
        app, dialog, _ = self._app_with_dialog([modified, added, untracked])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.status_entries.toggle_selection(2)

        app.action_restore_file()

        dialog.assert_confirm(
            "Restore 3 file(s) to HEAD?",
            [
                "git restore --source=HEAD --staged --worktree -- pkg/m.py",
                "git restore --staged -- pkg/new.py",
                "git clean -f -- pkg/new.py",
                "git clean -f -- scratch.txt",
            ],
        )
        app.git.restore_file.assert_not_called()

    def test_restore_multi_selection_filters_out_ineligible(self):
        """Ignored files in a mixed selection must not leak into the popup."""
        modified = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/m.py")
        ignored = GitEntry(GitCode.IGNORED_IGNORED, "build/out.log")
        app, dialog, _ = self._app_with_dialog([modified, ignored])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_restore_file()

        dialog.assert_confirm(
            "Restore 1 file(s) to HEAD?",
            ["git restore --source=HEAD --staged --worktree -- pkg/m.py"],
        )

    def test_restore_multi_selection_all_ineligible_notifies(self):
        ignored = GitEntry(GitCode.IGNORED_IGNORED, "build/out.log")
        app, dialog, _ = self._app_with_dialog([ignored])
        app.status_entries.toggle_selection(0)
        with patch.object(app, "notify") as notify:
            app.action_restore_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("No selected files can be restored")

    def test_confirming_restore_runs_git_restore_file_and_reloads(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry])
        app.action_restore_file()

        with patch.object(app, "_load_status"):
            dialog.confirm()

        app.git.restore_file.assert_called_once_with(entry)

    def test_confirming_batch_restore_runs_each_entry(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.action_restore_file()

        with patch.object(app, "_load_status"):
            dialog.confirm()

        # Entries run in file-list order (GitFilelist sorts by filename), not
        # the order they were handed to the constructor: "new.txt" < "pkg/a.py".
        self.assertEqual(
            [c.args for c in app.git.restore_file.call_args_list],
            [(b,), (a,)],
        )

    def test_cancelling_restore_with_n_does_not_touch_git(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry])
        app.action_restore_file()

        dialog.cancel()

        app.git.restore_file.assert_not_called()

    def test_restore_failure_surfaces_stderr_in_notification(self):
        """If any step of the restore chain fails, its stderr must land in
        the status notification so the user can diagnose without re-running
        the command from a shell."""
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry])
        app.git.restore_file.return_value = [
            MagicMock(returncode=1, stderr="pathspec did not match\n"),
        ]
        app.action_restore_file()
        with patch.object(app, "_load_status"), patch.object(app, "notify") as notify:
            dialog.confirm()

        notify.assert_called_with("git restore failed: pathspec did not match")

    def test_batch_restore_failure_lists_failed_filenames(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.git.restore_file.side_effect = [
            [MagicMock(returncode=0, stderr="")],
            [MagicMock(returncode=1, stderr="nope")],
        ]
        app.action_restore_file()
        with patch.object(app, "_load_status"), patch.object(app, "notify") as notify:
            dialog.confirm()

        notify.assert_called_with("git restore failed for 1 file(s): pkg/b.py")

    def test_restore_is_noop_without_highlight_or_selection(self):
        app, dialog, _ = self._app_with_dialog(
            [GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")], highlight_index=None
        )
        app.action_restore_file()
        dialog.assert_not_shown()


class TestDeleteConfirmation(unittest.TestCase):
    """DELETE removes file(s) via the operation that fits each file's status.
    The popup groups entries by status so the user reviews one command per
    status alongside the affected filenames."""

    def _app_with_dialog(self, entries, highlight_index=0):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist(entries)
        app.git.load_status.return_value = GitFilelist(entries)

        def delete_commands(entry):
            if entry.code.is_untracked:
                return [["git", "clean", "-f", "--", entry.filename]]
            if entry.code.staged.value == "A":
                return [
                    ["git", "rm", "-f", "--cached", "--", entry.filename],
                    ["git", "clean", "-f", "--", entry.filename],
                ]
            if entry.code.unstaged.value == "D":
                return [["git", "rm", "--cached", "--", entry.filename]]
            return [["git", "rm", "-f", "--", entry.filename]]

        app.git.delete_commands.side_effect = delete_commands
        app.git.delete_file.return_value = [MagicMock(returncode=0, stderr="")]

        dialog = _DialogProbe(app)
        status_list = MagicMock()
        status_list.index = highlight_index

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            return MagicMock()

        app.query_one.side_effect = query_one
        return app, dialog, status_list

    def test_delete_on_modified_file_shows_git_rm_force(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_delete_file()

        dialog.assert_confirm(
            "Delete pkg/a.py?",
            [
                "-- modified (staged) --",
                "  git rm -f -- <file>",
                "  pkg/a.py",
            ],
        )
        app.git.delete_file.assert_not_called()

    def test_delete_on_untracked_file_shows_git_clean(self):
        entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "scratch.txt")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_delete_file()

        dialog.assert_confirm(
            "Delete scratch.txt?",
            [
                "-- untracked --",
                "  git clean -f -- <file>",
                "  scratch.txt",
            ],
        )

    def test_delete_on_added_file_shows_unstage_then_clean(self):
        """Added-in-index files have no HEAD copy, so the popup must show
        both the unstage-from-cache and the clean steps so the user can see
        the worktree copy will be removed."""
        entry = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_delete_file()

        dialog.assert_confirm(
            "Delete pkg/new.py?",
            [
                "-- new file (staged) --",
                "  git rm -f --cached -- <file>",
                "  git clean -f -- <file>",
                "  pkg/new.py",
            ],
        )

    def test_delete_on_unstaged_delete_stages_the_removal(self):
        entry = GitEntry(GitCode.UNMODIFIED_DELETED, "pkg/gone.py")
        app, dialog, _ = self._app_with_dialog([entry])

        app.action_delete_file()

        dialog.assert_confirm(
            "Delete pkg/gone.py?",
            [
                "-- deleted (not staged) --",
                "  git rm --cached -- <file>",
                "  pkg/gone.py",
            ],
        )

    def test_delete_on_ignored_file_notifies_and_skips_dialog(self):
        entry = GitEntry(GitCode.IGNORED_IGNORED, "build/out.log")
        app, dialog, _ = self._app_with_dialog([entry])
        with patch.object(app, "notify") as notify:
            app.action_delete_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("No files can be deleted")

    def test_delete_on_already_staged_delete_is_skipped(self):
        """`D ` means the deletion is already staged — there's nothing left
        to do, so DELETE shouldn't surface a popup for it."""
        entry = GitEntry(GitCode.DELETED_UNMODIFIED, "pkg/gone.py")
        app, dialog, _ = self._app_with_dialog([entry])
        with patch.object(app, "notify") as notify:
            app.action_delete_file()
        dialog.assert_not_shown()
        notify.assert_called_once_with("No files can be deleted")

    def test_delete_multi_selection_groups_files_by_status(self):
        """Two files with the same status share one section header and one
        command line; a third file with a different status starts a new
        group separated by a blank line."""
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/b.py")
        untracked = GitEntry(GitCode.UNTRACKED_UNTRACKED, "scratch.txt")
        app, dialog, _ = self._app_with_dialog([a, b, untracked])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.status_entries.toggle_selection(2)

        app.action_delete_file()

        dialog.assert_confirm(
            "Delete 3 file(s)?",
            [
                "-- modified (staged) --",
                "  git rm -f -- <file>",
                "  pkg/a.py",
                "  pkg/b.py",
                "",
                "-- untracked --",
                "  git clean -f -- <file>",
                "  scratch.txt",
            ],
        )
        app.git.delete_file.assert_not_called()

    def test_delete_multi_selection_filters_out_ineligible(self):
        modified = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        ignored = GitEntry(GitCode.IGNORED_IGNORED, "build/out.log")
        app, dialog, _ = self._app_with_dialog([modified, ignored])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_delete_file()

        dialog.assert_confirm(
            "Delete 1 file(s)?",
            [
                "-- modified (staged) --",
                "  git rm -f -- <file>",
                "  pkg/a.py",
            ],
        )

    def test_confirming_delete_runs_git_delete_file_and_reloads(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry])
        app.action_delete_file()

        with patch.object(app, "_load_status"):
            dialog.confirm()

        app.git.delete_file.assert_called_once_with(entry)

    def test_confirming_batch_delete_runs_each_entry(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.action_delete_file()

        with patch.object(app, "_load_status"):
            dialog.confirm()

        # Entries run in file-list order (GitFilelist sorts by filename), not
        # the order they were handed to the constructor: "new.txt" < "pkg/a.py".
        self.assertEqual(
            [c.args for c in app.git.delete_file.call_args_list],
            [(b,), (a,)],
        )

    def test_cancelling_delete_with_n_does_not_touch_git(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialog, _ = self._app_with_dialog([entry])
        app.action_delete_file()

        dialog.cancel()

        app.git.delete_file.assert_not_called()

    def test_batch_delete_failure_lists_failed_filenames(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/b.py")
        app, dialog, _ = self._app_with_dialog([a, b])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.git.delete_file.side_effect = [
            [MagicMock(returncode=0, stderr="")],
            [MagicMock(returncode=1, stderr="nope")],
        ]
        app.action_delete_file()
        with patch.object(app, "_load_status"), patch.object(app, "notify") as notify:
            dialog.confirm()

        notify.assert_called_with("delete failed for 1 file(s): pkg/b.py")


class TestConfirmDialogScrolling(unittest.TestCase):
    """When the command list is taller than the popup, arrow / page keys
    scroll the inner ScrollableContainer. Y/N/Esc still close the dialog."""

    def _open_stage_dialog(self, num_files):
        app = _mock_app()
        entries = [GitEntry(GitCode.UNMODIFIED_MODIFIED, f"pkg/f{i}.py") for i in range(num_files)]
        app.status_entries = GitFilelist(entries)
        app.git.stage_command.side_effect = lambda f: ["git", "add", "--", f]

        dialog = _DialogProbe(app)
        status_list = MagicMock()
        status_list.index = 0

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            return MagicMock()

        app.query_one.side_effect = query_one
        for i in range(num_files):
            app.status_entries.toggle_selection(i)
        app.action_stage_file()
        return app, dialog

    def _press(self, key):
        """Send `key` to a freshly-pushed dialog, returning its scroll target."""
        _app, dialog = self._open_stage_dialog(20)
        screen = dialog.assert_open()
        container = MagicMock()
        with (
            patch.object(ConfirmDialog, "query_one", return_value=container),
            patch.object(ConfirmDialog, "dismiss") as dismiss,
        ):
            screen.on_key(_key_event(key))
        return container, dismiss

    def test_down_arrow_scrolls_dialog_without_closing(self):
        container, dismiss = self._press("down")

        container.scroll_down.assert_called_once_with(animate=False)
        dismiss.assert_not_called()

    def test_up_arrow_scrolls_dialog_without_closing(self):
        container, dismiss = self._press("up")

        container.scroll_up.assert_called_once_with(animate=False)
        dismiss.assert_not_called()

    def test_pagedown_scrolls_dialog(self):
        container, _ = self._press("pagedown")

        container.scroll_page_down.assert_called_once_with(animate=False)

    def test_home_end_scroll_dialog(self):
        for key, method in (("home", "scroll_home"), ("end", "scroll_end")):
            with self.subTest(key=key):
                container, _ = self._press(key)
                getattr(container, method).assert_called_once_with(animate=False)

    def test_status_list_no_longer_reaches_up_to_the_app_for_scrolling(self):
        """The old design had StatusList.on_key call back into the app to
        forward scroll keys, because ListView's cursor bindings fired before
        App.on_key saw them. A ModalScreen takes the StatusList out of the
        focus chain entirely, so up/down never reach it — the dialog scrolls
        itself and this plumbing is gone."""
        from gitnc.app import StatusList

        self.assertFalse(hasattr(GitNightCommanderApp, "_try_scroll_confirm_dialog"))

        app = _mock_app()
        app.query_one.side_effect = lambda sel, *a, **k: MagicMock()
        fake = MagicMock()
        type(fake).app = property(lambda self: app)
        event = _key_event("down")

        StatusList.on_key(fake, event)

        # Falls straight through to ListView's own cursor navigation.
        event.stop.assert_not_called()
        event.prevent_default.assert_not_called()

    def test_status_list_shift_up_still_extends_selection_when_dialog_closed(self):
        """With no dialog open, StatusList.on_key must keep its original
        behavior (shift+up extends selection)."""
        from gitnc.app import StatusList

        app = _mock_app()
        app._pending_confirm = None
        app.query_one.side_effect = lambda sel, *a, **k: MagicMock()
        extend = MagicMock()
        app._extend_status_selection = extend

        fake = MagicMock()
        type(fake).app = property(lambda self: app)
        event = MagicMock()
        event.key = "shift+up"

        StatusList.on_key(fake, event)

        extend.assert_called_once_with(-1)

    def test_status_list_up_arrow_is_unchanged_when_dialog_closed(self):
        """Without an open dialog, up/down must fall through so ListView's
        cursor navigation still moves the highlight."""
        from gitnc.app import StatusList

        app = _mock_app()
        app._pending_confirm = None
        app.query_one.side_effect = lambda sel, *a, **k: MagicMock()

        fake = MagicMock()
        type(fake).app = property(lambda self: app)
        event = MagicMock()
        event.key = "up"

        StatusList.on_key(fake, event)

        event.stop.assert_not_called()
        event.prevent_default.assert_not_called()

    def test_confirm_dialog_has_bounded_command_list_height(self):
        """The popup must cap the commands area so the dialog itself doesn't
        grow taller than the screen when many files are selected — the cap is
        what makes scrolling necessary in the first place."""
        self.assertIn("max-height", ConfirmDialog.DEFAULT_CSS)
        self.assertIn("#confirm-commands", ConfirmDialog.DEFAULT_CSS)


class TestConfirmDialogWidth(unittest.TestCase):
    """The popup is sized from the file list it is showing.

    `c` on a deep path used to open a dialog whose commands ran past the
    right edge and had to be scrolled to; now the box grows to the widest
    line, stops at the screen edge, and marks whatever didn't fit.
    """

    def _screen(self, width):
        """Patch in an app of `width` columns — the stubs have no screen."""
        app = MagicMock()
        app.size.width = width
        return patch.object(ConfirmDialog, "app", new_callable=PropertyMock, return_value=app)

    def _dialog(self, commands, prompt="Stage 1 file(s) for commit?"):
        return ConfirmDialog(prompt=prompt, commands=commands)

    def test_width_follows_the_widest_command_line(self):
        dialog = self._dialog(["git add -- " + "a" * 60])
        with self._screen(200):
            self.assertEqual(dialog.text_width(), len("$ git add -- ") + 60)

    def test_prompt_and_hint_are_measured_too(self):
        """They share the box, so a wide one widens it rather than wrapping."""
        dialog = self._dialog(["git add -- a.py"], prompt="p" * 80)
        with self._screen(200):
            self.assertEqual(dialog.text_width(), 80)
            self.assertEqual(dialog.text_width(hint="h" * 90), 90)

    def test_width_stops_at_the_screen_edge(self):
        dialog = self._dialog(["git add -- " + "a" * 400])
        with self._screen(80):
            self.assertEqual(dialog.text_width(), 80 - CONFIRM_DIALOG_CHROME_WIDTH)

    def test_short_file_list_keeps_a_readable_minimum_width(self):
        dialog = self._dialog(["git add -- a"], prompt="Stage?")
        with self._screen(200):
            self.assertEqual(dialog.text_width(), CONFIRM_DIALOG_MIN_TEXT_WIDTH)

    def test_minimum_width_never_overflows_a_narrow_screen(self):
        dialog = self._dialog(["git add -- a"], prompt="Stage?")
        narrow = CONFIRM_DIALOG_MIN_TEXT_WIDTH
        with self._screen(narrow):
            self.assertEqual(dialog.text_width(), narrow - CONFIRM_DIALOG_CHROME_WIDTH)

    def test_lines_that_do_not_fit_are_truncated_with_a_marker(self):
        dialog = self._dialog(["git add -- " + "a" * 400, "git add -- b.py"])
        with self._screen(80):
            lines = dialog.command_lines(dialog.text_width())

        self.assertEqual(len(lines[0]), 80 - CONFIRM_DIALOG_CHROME_WIDTH)
        self.assertTrue(lines[0].endswith(TRUNCATION_MARKER))
        # A name that fits is left alone, marker included.
        self.assertEqual(lines[1], "$ git add -- b.py")

    def test_a_scrolling_list_leaves_room_for_its_scrollbar(self):
        """Sized without it, the scrollbar lands past the border and gets
        clipped — the one hint that the list continues below disappears."""
        rows = CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS + 1
        dialog = self._dialog(["git add -- " + "a" * 400] * rows)
        with self._screen(80):
            self.assertEqual(
                dialog.text_width(),
                80 - CONFIRM_DIALOG_CHROME_WIDTH - CONFIRM_DIALOG_SCROLLBAR_WIDTH,
            )
            self.assertEqual(dialog.scrollbar_width(), CONFIRM_DIALOG_SCROLLBAR_WIDTH)

    def test_a_list_that_fits_reserves_nothing(self):
        dialog = self._dialog(["git add -- a.py"] * CONFIRM_DIALOG_VISIBLE_COMMAND_ROWS)

        self.assertEqual(dialog.scrollbar_width(), 0)

    def test_unmeasured_screen_leaves_the_lines_and_the_width_alone(self):
        """Before the dialog is mounted there is nothing to size against, so
        the CSS `width: auto` sizes the box and nothing is cut."""
        dialog = self._dialog(["git add -- " + "a" * 400])

        self.assertEqual(dialog.text_width(), 0)
        self.assertEqual(dialog.command_lines(dialog.text_width()), dialog.command_lines())

    def test_dialog_may_use_the_full_screen_width(self):
        """The box used to stop at 90% of the screen, which cut the file list
        short for no reason once it is sized from its content."""
        self.assertNotIn("max-width: 90%", ConfirmDialog.DEFAULT_CSS)


class TestTruncateToWidth(unittest.TestCase):
    def test_text_that_fits_is_returned_unchanged(self):
        self.assertEqual(_truncate_to_width("pkg/a.py", 8), "pkg/a.py")

    def test_marker_replaces_the_tail_rather_than_extending_the_line(self):
        cut = _truncate_to_width("pkg/some/deep/file.py", 10)

        self.assertEqual(len(cut), 10)
        self.assertEqual(cut, "pkg/some/" + TRUNCATION_MARKER)

    def test_width_smaller_than_the_marker_yields_what_fits(self):
        self.assertEqual(_truncate_to_width("pkg/a.py", 1), TRUNCATION_MARKER[:1])

    def test_no_limit_means_no_truncation(self):
        self.assertEqual(_truncate_to_width("pkg/a.py", 0), "pkg/a.py")


class TestSettingsDialog(unittest.TestCase):
    """The settings dialog is a ModalScreen that owns every key it receives.

    As a screen it can't be focused before it is pushed, which is what the old
    overlay widget needed an `allow_focus()` override to prevent: Textual's
    AUTO_FOCUS check tests `visibility`, not `display`, so a hidden overlay
    could win the race on mount and swallow every key.
    """

    def test_is_a_modal_screen_that_takes_no_auto_focus(self):
        self.assertTrue(issubclass(SettingsDialog, ModalScreen))
        # Nothing inside should take focus — the screen handles keys itself,
        # and this also stops the app's AUTO_FOCUS from applying here.
        self.assertIsNone(SettingsDialog.AUTO_FOCUS)

    def test_app_auto_focus_targets_the_file_list(self):
        self.assertEqual(GitNightCommanderApp.AUTO_FOCUS, "#status_list")

    def test_state_defaults_before_any_edit(self):
        dialog = SettingsDialog()

        self.assertEqual(dialog._cursor, 0)
        self.assertEqual(
            dialog.get_values(),
            SettingsValues(
                branch_prefix=False,
                draft_command=COMMIT_DRAFT_COMMAND_DEFAULT,
                draft_prompt=COMMIT_DRAFT_PROMPT_DEFAULT,
                default_branch=DEFAULT_BRANCH_DEFAULT,
            ),
        )

    def test_constructor_seeds_the_current_settings(self):
        dialog = SettingsDialog(
            branch_prefix=True,
            draft_command="claude -p",
            draft_prompt="Draft a message for:",
            default_branch="main",
        )

        self.assertEqual(
            dialog.get_values(),
            SettingsValues(
                branch_prefix=True,
                draft_command="claude -p",
                draft_prompt="Draft a message for:",
                default_branch="main",
            ),
        )

    def test_the_drafting_tool_is_a_free_text_command(self):
        """The predefined tool list is gone: the user names a command, so any
        tool works without the app knowing about it."""
        dialog = SettingsDialog(draft_command="")
        for _ in range(2):
            dialog.on_key(_key_event("down"))
        self.assertEqual(dialog._cursor, 2)

        for key, character in (("c", "c"), ("l", "l"), ("space", None), ("minus", "-")):
            dialog.on_key(_key_event(key, character=character))

        self.assertEqual(dialog.get_values().draft_command, "cl -")

    def test_the_prompt_template_is_editable_too(self):
        dialog = SettingsDialog(draft_prompt="ab")
        for _ in range(3):
            dialog.on_key(_key_event("down"))
        self.assertEqual(dialog._cursor, 3)

        dialog.on_key(_key_event("backspace"))
        dialog.on_key(_key_event("c", character="c"))

        self.assertEqual(dialog.get_values().draft_prompt, "ac")

    def test_space_types_into_a_text_row_instead_of_toggling(self):
        """Space is the checkbox key, but on a text row it has to be a space
        or command lines and prompts couldn't be typed at all."""
        dialog = SettingsDialog(draft_prompt="a")
        for _ in range(3):
            dialog.on_key(_key_event("down"))

        dialog.on_key(_key_event("space"))

        self.assertEqual(dialog.get_values().draft_prompt, "a ")
        self.assertFalse(dialog.get_values().branch_prefix)

    def test_cursor_wraps_over_every_row(self):
        dialog = SettingsDialog()

        dialog.on_key(_key_event("up"))

        self.assertEqual(dialog._cursor, SETTINGS_ROW_COUNT - 1)

    def test_typing_before_mount_does_not_raise(self):
        """Keys can arrive before compose() has run; the redraw has nothing to
        paint but the edit must still be recorded."""
        dialog = SettingsDialog()

        dialog.on_key(_key_event("z", character="z"))

        self.assertEqual(dialog._default_branch, DEFAULT_BRANCH_DEFAULT + "z")

    def test_tab_and_space_are_handled_by_the_dialog(self):
        """Both keys would otherwise be taken by the StatusList underneath or
        Textual's screen-level focus cycling."""
        dialog = SettingsDialog()

        dialog.on_key(_key_event("tab"))
        self.assertEqual(dialog._cursor, 1)
        dialog.on_key(_key_event("space"))
        self.assertTrue(dialog._branch_prefix)

    def test_enter_dismisses_with_the_edited_values(self):
        dialog = SettingsDialog(default_branch="main")
        dialog.on_key(_key_event("down"))
        dialog.on_key(_key_event("space"))

        with patch.object(SettingsDialog, "dismiss") as dismiss:
            dialog.on_key(_key_event("enter"))

        self.assertEqual(dismiss.call_args.args[0].branch_prefix, True)
        self.assertEqual(dismiss.call_args.args[0].default_branch, "main")

    def test_escape_dismisses_with_none(self):
        dialog = SettingsDialog()

        with patch.object(SettingsDialog, "dismiss") as dismiss:
            dialog.on_key(_key_event("escape"))

        dismiss.assert_called_once_with(None)

    def test_action_settings_seeds_the_dialog_from_saved_settings(self):
        app = _mock_app()
        with patch.object(
            app,
            "_load_settings",
            return_value={
                "branch_prefix_in_commits": True,
                "commit_draft_command": "claude -p",
                "commit_draft_prompt": "Draft a message for:",
                "default_branch": "main",
            },
        ):
            app.action_settings()

        screen = _pushed_screen(app)
        self.assertIsInstance(screen, SettingsDialog)
        self.assertEqual(
            screen.get_values(),
            SettingsValues(
                branch_prefix=True,
                draft_command="claude -p",
                draft_prompt="Draft a message for:",
                default_branch="main",
            ),
        )

    def test_non_string_settings_fall_back_to_the_defaults(self):
        """settings.json is hand-editable, so anything at all can turn up
        under a key the dialog expects to be text."""
        app = _mock_app()
        with patch.object(
            app,
            "_load_settings",
            return_value={"commit_draft_command": 7, "commit_draft_prompt": None},
        ):
            app.action_settings()

        values = _pushed_screen(app).get_values()
        self.assertEqual(values.draft_command, COMMIT_DRAFT_COMMAND_DEFAULT)
        self.assertEqual(values.draft_prompt, COMMIT_DRAFT_PROMPT_DEFAULT)

    def test_saving_writes_the_values_to_settings(self):
        app = _mock_app()
        saved: dict[str, object] = {}
        with (
            patch.object(app, "_load_settings", return_value={"theme": "midnight-commander"}),
            patch.object(app, "_save_settings", side_effect=lambda s: saved.update(s) or True),
            patch.object(app, "notify") as notify,
        ):
            app._settings_result(
                SettingsValues(
                    branch_prefix=True,
                    draft_command="claude -p",
                    draft_prompt="Draft a message for:",
                    default_branch="main",
                )
            )

        self.assertEqual(saved["branch_prefix_in_commits"], True)
        self.assertEqual(saved["commit_draft_command"], "claude -p")
        self.assertEqual(saved["commit_draft_prompt"], "Draft a message for:")
        self.assertEqual(saved["default_branch"], "main")
        # Unrelated settings survive the round-trip.
        self.assertEqual(saved["theme"], "midnight-commander")
        notify.assert_called_once_with("Settings saved")

    @staticmethod
    def _rendered_lines(dialog) -> list[str]:
        """What `_redraw()` paints, one line per row."""
        rendered: list[str] = []
        with patch.object(
            SettingsDialog,
            "query_one",
            return_value=MagicMock(update=lambda text: rendered.append(text)),
        ):
            dialog._redraw()
        return rendered[-1].split("\n")

    def test_the_drafting_settings_sit_under_an_experimental_heading(self):
        """The drafting tool is the experimental part of the dialog, so the
        three settings it owns are grouped behind a heading of their own —
        below the branch settings, which are not."""
        lines = self._rendered_lines(SettingsDialog())

        heading = next(i for i, line in enumerate(lines) if "Experimental" in line)
        for label in ("Command:", "Prompt:", "Parse suggestions"):
            row = next(i for i, line in enumerate(lines) if label in line)
            self.assertGreater(row, heading, label)
        for label in ("Default branch:", "Use branch name as prefix"):
            row = next(i for i, line in enumerate(lines) if label in line)
            self.assertLess(row, heading, label)

    @staticmethod
    def _field_body(lines: list[str]) -> list[str]:
        """The text inside the prompt field: the rows between its two border
        lines, without their markup and side borders."""
        top = next(i for i, line in enumerate(lines) if "┌" in line)
        bottom = next(i for i, line in enumerate(lines) if "└" in line)
        return [_strip_markup(line).strip(" │") for line in lines[top + 1 : bottom]]

    @staticmethod
    def _caret_cell(lines: list[str]) -> tuple[int, int, str] | None:
        """Where the caret is drawn — (line, column, the character under it) —
        or None when nothing on screen carries it."""
        for index, line in enumerate(lines):
            match = re.search(r"\[reverse\](.)\[/reverse\]", line)
            if match is not None:
                return index, len(_strip_markup(line[: match.start()])), match.group(1)
        return None

    @staticmethod
    def _focus_prompt(dialog) -> None:
        """Tab down to the prompt field, the way a user reaches it."""
        while dialog._cursor != SETTINGS_ROW_PROMPT:
            dialog.on_key(_key_event("tab"))

    @staticmethod
    def _wrapped(text: str, *, width: int) -> list[str]:
        """Just the text of each wrapped line."""
        return [line.text for line in _wrap_field_text(text, width=width)]

    def test_the_prompt_is_drawn_as_a_framed_text_field(self):
        """The template is a paragraph rather than a word, so it gets a field
        that marks where the text is instead of a value trailing its label."""
        dialog = SettingsDialog(draft_prompt="Draft a message for:")
        self._focus_prompt(dialog)

        lines = self._rendered_lines(dialog)

        label = next(i for i, line in enumerate(lines) if "Prompt:" in line)
        self.assertIn("┌", lines[label + 1])
        body = self._field_body(lines)
        self.assertIn("Draft a message for:", body[0])
        # A value shorter than the field still gets the field's full height.
        self.assertEqual(len(body), SETTINGS_FIELD_MIN_LINES)
        # The caret marks the row being typed into, and only that row: the
        # field is entered with it after the last character.
        caret = self._caret_cell(lines)
        assert caret is not None
        self.assertEqual(caret[0], label + 2)
        dialog.on_key(_key_event("tab"))
        self.assertIsNone(self._caret_cell(self._rendered_lines(dialog)))

    def test_the_prompt_wraps_at_word_boundaries_over_several_lines(self):
        """A template runs past one line, and reading it back is the point of
        showing it at all — so it wraps instead of scrolling out of sight."""
        dialog = SettingsDialog(draft_prompt=" ".join(["alpha"] * 40))

        body = [line for line in self._field_body(self._rendered_lines(dialog)) if line.strip()]

        self.assertGreater(len(body), 1)
        for line in body:
            # No word is broken across the wrap.
            self.assertNotIn("alph ", line)
            self.assertTrue(line.strip().startswith("alpha"))
        self.assertEqual(sum(line.count("alpha") for line in body), 40)

    def test_wrapping_keeps_what_is_being_typed(self):
        """The wrap is not `textwrap.wrap()`: a field is typed into, so the
        space after a finished word survives to push the caret along, and an
        empty value is still one line for the field to draw."""
        self.assertEqual(self._wrapped("", width=10), [""])
        self.assertEqual(self._wrapped("one two ", width=10), ["one two "])
        self.assertEqual(self._wrapped("one two three", width=10), ["one two ", "three"])
        # A word with nowhere to break is broken where it fills the line.
        self.assertEqual(self._wrapped("x" * 12, width=10), ["x" * 10, "xx"])
        # A saved template's own newlines keep their shape.
        self.assertEqual(self._wrapped("one\ntwo", width=10), ["one", "two"])

    def test_each_wrapped_line_knows_where_it_starts_in_the_value(self):
        """That offset is what maps the caret between the value and the
        screen, so the newline a paragraph ends on has to be counted."""
        self.assertEqual(
            _wrap_field_text("one two three", width=10),
            [FieldLine(start=0, text="one two "), FieldLine(start=8, text="three")],
        )
        self.assertEqual(
            _wrap_field_text("one\ntwo", width=10),
            [FieldLine(start=0, text="one"), FieldLine(start=4, text="two")],
        )

    def test_left_and_right_position_the_caret_inside_the_field(self):
        """The point of the arrows: typing goes where the caret is, not at
        the end of whatever was already there."""
        dialog = SettingsDialog(draft_prompt="ac")
        self._focus_prompt(dialog)

        dialog.on_key(_key_event("left"))
        dialog.on_key(_key_event("b", character="b"))

        self.assertEqual(dialog.get_values().draft_prompt, "abc")
        # And the caret stays after what was typed.
        dialog.on_key(_key_event("d", character="d"))
        self.assertEqual(dialog.get_values().draft_prompt, "abdc")

    def test_backspace_takes_the_character_in_front_of_the_caret(self):
        dialog = SettingsDialog(draft_prompt="abc")
        self._focus_prompt(dialog)

        for _ in range(2):
            dialog.on_key(_key_event("left"))
        dialog.on_key(_key_event("backspace"))

        self.assertEqual(dialog.get_values().draft_prompt, "bc")
        # At the start of the value there is nothing to delete.
        dialog.on_key(_key_event("left"))
        dialog.on_key(_key_event("backspace"))
        self.assertEqual(dialog.get_values().draft_prompt, "bc")

    def test_the_caret_stops_at_the_two_ends_of_the_value(self):
        dialog = SettingsDialog(draft_prompt="ab")
        self._focus_prompt(dialog)

        for _ in range(5):
            dialog.on_key(_key_event("left"))
        self.assertEqual(dialog._caret, 0)
        for _ in range(5):
            dialog.on_key(_key_event("right"))
        self.assertEqual(dialog._caret, 2)

    def test_up_and_down_move_the_caret_between_the_wrapped_lines(self):
        """In a field the arrows are the caret's — the row cursor stays put
        until Tab or Enter is pressed."""
        dialog = SettingsDialog(draft_prompt="alpha " * 40)
        self._focus_prompt(dialog)
        lines = _wrap_field_text(dialog.get_values().draft_prompt, width=SETTINGS_FIELD_TEXT_WIDTH)
        self.assertGreater(len(lines), 2)

        dialog.on_key(_key_event("up"))

        self.assertEqual(dialog._cursor, SETTINGS_ROW_PROMPT)
        # One display line back, in the same column.
        self.assertEqual(dialog._caret, lines[-2].start + len(lines[-1].text))
        dialog.on_key(_key_event("down"))
        self.assertEqual(dialog._caret, len(dialog.get_values().draft_prompt))

    def test_the_arrows_never_leave_the_field(self):
        """Up on the first line and down on the last go to the ends of the
        value — leaving the field is what Tab and Enter are for."""
        dialog = SettingsDialog(draft_prompt="alpha " * 40)
        self._focus_prompt(dialog)

        for _ in range(20):
            dialog.on_key(_key_event("up"))

        self.assertEqual(dialog._cursor, SETTINGS_ROW_PROMPT)
        self.assertEqual(dialog._caret, 0)
        for _ in range(20):
            dialog.on_key(_key_event("down"))
        self.assertEqual(dialog._cursor, SETTINGS_ROW_PROMPT)
        self.assertEqual(dialog._caret, len(dialog.get_values().draft_prompt))

    def test_tab_and_enter_are_what_leave_the_field(self):
        dialog = SettingsDialog()
        self._focus_prompt(dialog)

        dialog.on_key(_key_event("tab"))
        self.assertEqual(dialog._cursor, SETTINGS_ROW_PARSE)

        self._focus_prompt(dialog)
        with patch.object(SettingsDialog, "dismiss") as dismiss:
            dialog.on_key(_key_event("enter"))
        dismiss.assert_called_once()

    def test_a_row_is_entered_with_its_caret_at_the_end(self):
        """Where a value that is only ever appended to would have left it,
        so reaching a row and typing needs no arrow keys at all."""
        dialog = SettingsDialog(draft_prompt="abc")
        self._focus_prompt(dialog)
        dialog.on_key(_key_event("left"))

        dialog.on_key(_key_event("tab"))
        self._focus_prompt(dialog)

        self.assertEqual(dialog._caret, 3)

    def test_the_key_hint_says_what_the_arrows_do_in_a_field(self):
        """The dialog's arrows mean two different things, so the line under
        it has to follow the cursor."""
        dialog = SettingsDialog()

        self.assertIn("↑↓/Tab move", self._rendered_lines(dialog)[-1])

        self._focus_prompt(dialog)

        hint = self._rendered_lines(dialog)[-1]
        self.assertIn("move the caret", hint)
        self.assertIn("Tab leaves", hint)

    def test_the_frame_keeps_its_width_wherever_the_caret_is(self):
        """The caret takes a cell of its own past the end of a line, which
        has to come out of the padding rather than out of the border."""
        for prompt in ("", "x" * SETTINGS_FIELD_TEXT_WIDTH, "alpha " * 40):
            dialog = SettingsDialog(draft_prompt=prompt)
            self._focus_prompt(dialog)
            for presses in range(12):
                for line in self._rendered_lines(dialog):
                    if "│" in line:
                        plain = _strip_markup(line).replace("\\[", "[")
                        self.assertEqual(len(plain), SETTINGS_SECTION_WIDTH, (prompt, presses))
                dialog.on_key(_key_event("left"))

    def test_the_field_scrolls_to_wherever_the_caret_is(self):
        """A caret arrowed up past the top of a capped field has to come
        back into view, or it would be somewhere the user can't see."""
        dialog = SettingsDialog(draft_prompt="alpha " * 400)
        self._focus_prompt(dialog)

        for _ in range(SETTINGS_FIELD_MAX_LINES + 2):
            dialog.on_key(_key_event("up"))

        caret = self._caret_cell(self._rendered_lines(dialog))
        assert caret is not None
        top = next(i for i, line in enumerate(self._rendered_lines(dialog)) if "┌" in line)
        self.assertEqual(caret[0], top + 1)

    def test_the_field_grows_with_the_value_up_to_its_cap(self):
        """Past the cap the field scrolls, keeping the last lines — that is
        where the caret is."""
        dialog = SettingsDialog(draft_prompt="alpha " * 400 + "omega")
        self._focus_prompt(dialog)

        lines = self._rendered_lines(dialog)
        body = self._field_body(lines)

        self.assertEqual(len(body), SETTINGS_FIELD_MAX_LINES)
        self.assertTrue(body[-1].endswith("omega"))
        # The caret is on the last line, in the cell after the last character.
        caret = self._caret_cell(lines)
        assert caret is not None
        row, _, character = caret
        self.assertEqual(row, next(i for i, line in enumerate(lines) if "└" in line) - 1)
        self.assertEqual(character, " ")

    def test_the_suggestion_row_is_a_checkbox_under_the_drafting_tool(self):
        """It belongs to the drafting tool, so it sits with the command and
        the prompt rather than off on its own."""
        lines = self._rendered_lines(SettingsDialog())

        row = next(i for i, line in enumerate(lines) if "Parse suggestions" in line)
        prompt = next(i for i, line in enumerate(lines) if "Prompt:" in line)
        self.assertIn("[ ]", lines[row])
        self.assertGreater(row, prompt)

    def test_space_toggles_parsing_suggestions(self):
        dialog = SettingsDialog()
        # Tab, not down: the row above this one is the prompt field, where
        # down belongs to the caret.
        for _ in range(SETTINGS_ROW_PARSE):
            dialog.on_key(_key_event("tab"))
        self.assertEqual(dialog._cursor, SETTINGS_ROW_PARSE)

        dialog.on_key(_key_event("space"))

        self.assertTrue(dialog.get_values().parse_suggestions)
        # The other checkbox is untouched.
        self.assertFalse(dialog.get_values().branch_prefix)

    def test_the_setting_round_trips_through_the_dialog(self):
        app = _mock_app()
        saved: dict[str, object] = {}
        with patch.object(
            app, "_load_settings", return_value={"commit_draft_parse_suggestions": True}
        ):
            app.action_settings()
        self.assertTrue(_pushed_screen(app).get_values().parse_suggestions)

        with (
            patch.object(app, "_load_settings", return_value={}),
            patch.object(app, "_save_settings", side_effect=lambda s: saved.update(s) or True),
            patch.object(app, "notify"),
        ):
            app._settings_result(
                SettingsValues(
                    branch_prefix=False,
                    draft_command="tool",
                    draft_prompt="p",
                    default_branch="main",
                    parse_suggestions=True,
                )
            )

        self.assertEqual(saved["commit_draft_parse_suggestions"], True)

    def test_cancelling_writes_nothing(self):
        app = _mock_app()
        with (
            patch.object(app, "_save_settings") as save,
            patch.object(app, "notify") as notify,
        ):
            app._settings_result(None)

        save.assert_not_called()
        notify.assert_not_called()

    def test_unwritable_settings_file_is_reported(self):
        app = _mock_app()
        with (
            patch.object(app, "_load_settings", return_value={}),
            patch.object(app, "_save_settings", return_value=False),
            patch.object(app, "notify") as notify,
        ):
            app._settings_result(
                SettingsValues(
                    branch_prefix=False,
                    draft_command="",
                    draft_prompt="",
                    default_branch="main",
                )
            )

        notify.assert_called_once_with("Settings saved (could not write to disk)")


class TestMenuStyling(unittest.TestCase):
    def test_dropdown_menu_focus_style_removes_inner_border(self):
        self.assertIn("DropdownMenu OptionList:focus", DropdownMenu.DEFAULT_CSS)
        self.assertIn("outline: none;", DropdownMenu.DEFAULT_CSS)

    def test_file_list_mode_marked_with_radio_glyphs(self):
        """The two file-list modes are mutually exclusive, so they read as a
        radio group rather than an asterisk sitting in the label text."""
        app = GitNightCommanderApp()
        for mode, on_label, off_label in (
            (MODE_SHORT, "Short file list", "Long file list"),
            (MODE_LONG, "Long file list", "Short file list"),
        ):
            with self.subTest(mode=mode):
                app.file_list_mode = mode
                labels = [_menu_plain_label(label) for label, _ in app._file_menu_items()]
                self.assertIn(f"{MENU_RADIO_ON}{MENU_MARKER_GAP}{on_label}", labels)
                self.assertIn(f"{MENU_RADIO_OFF}{MENU_MARKER_GAP}{off_label}", labels)
                self.assertFalse([label for label in labels if "*" in label])

    def test_file_menu_labels_all_start_in_the_same_column(self):
        """A one-cell marker gutter keeps every entry's text aligned, so
        switching mode can't shift item widths."""
        app = GitNightCommanderApp()
        for mode in (MODE_SHORT, MODE_LONG):
            with self.subTest(mode=mode):
                app.file_list_mode = mode
                prefixes = {
                    _menu_plain_label(label)[: len(MENU_RADIO_ON) + len(MENU_MARKER_GAP)]
                    for label, _ in app._file_menu_items()
                }
                self.assertEqual(
                    {p[-1] for p in prefixes},
                    {MENU_MARKER_GAP},
                )
                self.assertEqual(
                    {p[0] for p in prefixes},
                    {MENU_RADIO_ON, MENU_RADIO_OFF, MENU_MARKER_BLANK},
                )

    def test_dropdown_labels_carry_right_aligned_shortcut_hints(self):
        """Entries with a keyboard binding advertise it in a hint column, so
        the menu teaches the shortcut instead of hiding it."""
        app = GitNightCommanderApp()
        labels = _menu_option_labels(app._file_menu_items())
        by_text = {label.strip().split(" ")[0]: label for label in labels}
        self.assertTrue(by_text["Refresh"].endswith("F5"))
        self.assertTrue(by_text["Delete"].endswith("F8"))
        self.assertTrue(by_text["Commit"].endswith("C"))
        self.assertTrue(by_text["Quit"].endswith("F10"))
        # One column: every rendered label is the same width, and the hints
        # end on the same cell.
        self.assertEqual(len({len(label) for label in labels}), 1)

    def test_dropdown_without_bindings_keeps_bare_labels(self):
        """A menu where nothing is bound gets no empty hint column."""
        self.assertEqual(
            _menu_option_labels([("Status", "view_status"), ("History", "view_history")]),
            ["Status", "History"],
        )

    def test_entry_that_opens_a_submenu_is_marked_with_an_arrow(self):
        """Options -> Theme opens a nested menu instead of acting, so it says
        so where a leaf entry advertises its shortcut."""
        labels = _menu_option_labels(OPTIONS_MENU)
        by_text = {label.strip().split(" ")[0]: label for label in labels}
        self.assertTrue(by_text["Theme"].endswith(MENU_SUBMENU_MARKER))
        self.assertNotIn(MENU_SUBMENU_MARKER, by_text["Settings"])
        # The arrow shares the hint column, so the labels stay one width.
        self.assertEqual(len({len(label) for label in labels}), 1)


class TestSubmenus(unittest.TestCase):
    """Nested menus come from the `SUBMENUS` registry: one entry gives a
    dropdown, the action that opens it, and the arrow on its parent entry."""

    def test_every_registered_submenu_marks_the_entry_that_opens_it(self):
        for submenu in SUBMENUS:
            with self.subTest(submenu=submenu.name):
                self.assertEqual(_menu_hint(submenu.action), MENU_SUBMENU_MARKER)

    def test_options_theme_entry_runs_the_registered_submenu_action(self):
        """The menu table takes the action from the registry, so the action
        the entry runs and the action that carries the arrow can't drift."""
        actions = {_menu_plain_label(label): action for label, action in OPTIONS_MENU}
        self.assertEqual(actions["Theme"], SUBMENUS_BY_NAME["theme"].action)

    @staticmethod
    def _cascade_app(*, label_x: int = 12, label_y: int = 0, row: int = 3) -> tuple[Any, Any, Any]:
        """An app wired up to open the theme submenu; returns parent & child.

        The parent menu reports a fixed width and puts the entry that opens
        the submenu on row *row*, so the assertions can name exact cells.
        """
        app = _mock_app()
        label, parent, child = MagicMock(), MagicMock(), MagicMock()
        label.region.x, label.region.y = label_x, label_y
        parent.menu_width = 15
        parent.index_of_action.return_value = row
        child.menu_width = 24
        app.query_one = MagicMock(
            side_effect=lambda selector, _type=None: {
                "#menu_options": label,
                "#dropdown_options": parent,
                "#dropdown_theme": child,
            }[selector]
        )
        return app, parent, child

    def test_open_submenu_cascades_off_the_row_that_opened_it(self):
        """Nested menus hang off their parent row: the child starts at the
        parent's right edge, and its first entry lines up with that row."""
        app, _parent, child = self._cascade_app(label_x=12, label_y=0, row=3)
        app.action_open_submenu("theme")
        # Parent top is one line below the menu bar, so its row 3 renders on
        # line 5 (top border + 3) — where the child's own first row lands.
        child.show_at.assert_called_once_with(12 + 15, 1 + 3)

    def test_open_submenu_keeps_its_parent_on_screen(self):
        """A cascade shows the trail: the parent menu stays open under the
        menu bar with its cursor on the entry that opened the child."""
        app, parent, _child = self._cascade_app()
        app.action_open_submenu("theme")
        parent.show_at.assert_called_once_with(12, 1)
        parent.highlight_action.assert_called_once_with(SUBMENUS_BY_NAME["theme"].action)
        parent.hide.assert_not_called()

    def test_open_submenu_hides_every_menu_but_the_parent(self):
        app, parent, _child = self._cascade_app()
        other = MagicMock()
        app.query = MagicMock(return_value=[other, parent])
        app.action_open_submenu("theme")
        other.hide.assert_called_once_with()
        parent.hide.assert_not_called()

    def test_cascade_flips_to_the_left_when_it_would_run_off_screen(self):
        app = _mock_app()
        screen = MagicMock()
        screen.size.width = 40
        with patch.object(type(app), "screen", new_callable=PropertyMock, return_value=screen):
            # 30 + 15 + 24 overruns a 40-column screen, so the child goes left.
            self.assertEqual(app._cascade_x(left=30, parent_width=15, width=24), 30 - 24)
            self.assertEqual(app._cascade_x(left=0, parent_width=15, width=24), 15)

    def test_dropdowns_are_positioned_absolutely(self):
        """`show_at` places menus in screen cells. A relative offset is
        measured from the visible overlay siblings instead, which puts a
        cascade one parent-width too far right the moment two menus are
        open at once."""
        self.assertIn("position: absolute", DropdownMenu.DEFAULT_CSS)

    def test_cascade_stays_on_the_right_without_a_screen_to_measure(self):
        """A non-running app has no screen stack to ask for a width."""
        app = _mock_app()
        self.assertEqual(app._cascade_x(left=30, parent_width=15, width=24), 45)

    def test_open_submenu_with_an_unknown_name_does_nothing(self):
        app = _mock_app()
        app.action_open_submenu("nope")
        app.query_one.assert_not_called()

    @staticmethod
    def _app_with_open_menu(dropdown_id: str) -> tuple[Any, Any]:
        """An app whose only visible dropdown is *dropdown_id*."""
        app = _mock_app()
        open_dropdown = MagicMock(id=dropdown_id, display=True)
        app.query = MagicMock(return_value=[open_dropdown])
        app._show_menu_by_index = MagicMock()
        return app, open_dropdown

    def test_escape_in_a_submenu_reopens_the_menu_it_was_opened_from(self):
        """A nested menu is reached through its parent, so Escape walks back
        out one level instead of dropping the user out of the menus."""
        app, _ = self._app_with_open_menu("dropdown_theme")
        app.action_escape()
        app._show_menu_by_index.assert_called_once_with(
            GitNightCommanderApp.MENU_ORDER.index("menu_options")
        )
        app.query_one.return_value.highlight_action.assert_called_once_with(
            SUBMENUS_BY_NAME["theme"].action
        )

    def test_escape_from_the_parent_menu_leaves_the_menus(self):
        """One level at a time: the second Escape is an ordinary close."""
        app, options = self._app_with_open_menu("dropdown_options")
        app.action_escape()
        app._show_menu_by_index.assert_not_called()
        options.hide.assert_called_once_with()

    def test_left_arrow_in_a_submenu_goes_back_to_the_parent(self):
        """A nested menu has no neighbours to cycle through, so left means
        back rather than "previous top-level menu"."""
        app, _ = self._app_with_open_menu("dropdown_theme")
        event = _key_event("left")
        app.on_key(event)
        app._show_menu_by_index.assert_called_once_with(
            GitNightCommanderApp.MENU_ORDER.index("menu_options")
        )
        event.stop.assert_called_once()

    def test_dropdown_highlights_the_entry_running_an_action(self):
        menu = DropdownMenu(OPTIONS_MENU)
        option_list = MagicMock(highlighted=None)
        menu.query_one = MagicMock(return_value=option_list)
        menu.highlight_action(SUBMENUS_BY_NAME["theme"].action)
        self.assertEqual(option_list.highlighted, 0)

    def test_dropdown_ignores_an_action_it_has_no_entry_for(self):
        menu = DropdownMenu(OPTIONS_MENU)
        menu.query_one = MagicMock()
        menu.highlight_action("no_such_action")
        menu.query_one.assert_not_called()


class TestMenuMnemonics(unittest.TestCase):
    """Turbo Vision / MC accelerators: every menu entry highlights one letter,
    Alt+letter opens a menu, and the letter alone picks an entry inside it."""

    def test_every_menu_bar_entry_declares_a_unique_accelerator(self):
        keys = [_menu_mnemonic_key(label) for label, _ in MENU_BAR]
        self.assertNotIn(None, keys)
        self.assertEqual(len(set(keys)), len(keys))

    def test_every_file_menu_entry_declares_a_unique_accelerator(self):
        app = GitNightCommanderApp()
        for menu in (app._file_menu_items(), VIEW_MENU, OPTIONS_MENU, HELP_MENU):
            with self.subTest(menu=[label for label, _ in menu]):
                keys = [_menu_mnemonic_key(label) for label, _ in menu]
                self.assertNotIn(None, keys)
                self.assertEqual(len(set(keys)), len(keys))

    def test_accelerator_marker_never_reaches_the_rendered_label(self):
        """The marker is a source-side annotation; what the user reads is the
        bare label with the letter highlighted."""
        app = GitNightCommanderApp()
        for label in _menu_option_labels(app._file_menu_items()):
            self.assertNotIn("&", label)

    def test_rendered_label_highlights_the_marked_letter(self):
        markup = _menu_option_markup([("&Status", "view_status")], style="bold yellow")
        self.assertEqual(markup, ["[bold yellow]S[/]tatus"])

    def test_label_without_a_marker_is_rendered_untouched(self):
        """Theme names carry no accelerator — too many of them to spell one."""
        markup = _menu_option_markup([("nord", "set_theme('nord')")], style="bold yellow")
        self.assertEqual(markup, ["nord"])

    def test_doubled_marker_escapes_to_a_literal_ampersand(self):
        self.assertEqual(
            _menu_option_markup([("Fetch && merge", "fetch")], style="u"),
            ["Fetch & merge"],
        )

    def test_hint_column_stays_aligned_with_accelerators_in_the_labels(self):
        """The marker is stripped before padding, so it can't widen a label."""
        app = GitNightCommanderApp()
        labels = _menu_option_labels(app._file_menu_items())
        self.assertEqual(len({len(label) for label in labels}), 1)

    def test_alt_letter_opens_the_matching_menu(self):
        app = _mock_app()
        for key, index in (("alt+f", 0), ("alt+r", 1), ("alt+v", 2), ("alt+o", 3), ("alt+h", 4)):
            with self.subTest(key=key):
                event = _key_event(key)
                with patch.object(app, "_show_menu_by_index") as show:
                    app.on_key(event)
                show.assert_called_once_with(index)
                event.stop.assert_called_once()

    def test_alt_letter_that_names_no_menu_is_left_alone(self):
        app = _mock_app()
        event = _key_event("alt+z")
        with patch.object(app, "_show_menu_by_index") as show:
            app.on_key(event)
        show.assert_not_called()
        event.stop.assert_not_called()

    def test_arrow_navigation_still_works_alongside_accelerators(self):
        app = _mock_app()
        with (
            patch.object(app, "_open_menu_index", return_value=0),
            patch.object(app, "_show_menu_by_index") as show,
        ):
            app.on_key(_key_event("right"))
        show.assert_called_once_with(1)

    def test_typing_an_entry_letter_runs_that_entry(self):
        dropdown = DropdownMenu(VIEW_MENU)
        dropdown.display = True
        app = MagicMock()
        run_action = []

        async def run(action):
            run_action.append(action)

        app.run_action = run
        with patch.object(DropdownMenu, "app", app):
            asyncio.run(dropdown.on_key(_key_event("h", character="h")))
        self.assertEqual(run_action, ["view_history"])
        self.assertFalse(dropdown.display)

    def test_unmatched_letter_is_swallowed_while_a_menu_is_open(self):
        """`c` would otherwise reach the app's commit binding behind the open
        menu."""
        dropdown = DropdownMenu(VIEW_MENU)
        dropdown.display = True
        event = _key_event("c", character="c")
        asyncio.run(dropdown.on_key(event))
        event.stop.assert_called_once()
        self.assertTrue(dropdown.display)

    def test_navigation_keys_are_left_to_the_option_list(self):
        dropdown = DropdownMenu(VIEW_MENU)
        for key, character in (("down", None), ("enter", "\r"), ("space", " ")):
            with self.subTest(key=key):
                event = _key_event(key, character=character)
                asyncio.run(dropdown.on_key(event))
                event.stop.assert_not_called()

    def test_alt_letter_passes_through_an_open_menu(self):
        """Textual reports alt+f with character "f"; claiming it here would
        stop the menu bar from switching menus while one is open."""
        dropdown = DropdownMenu(VIEW_MENU)
        event = _key_event("alt+f", character="f")
        asyncio.run(dropdown.on_key(event))
        event.stop.assert_not_called()

    def test_menu_label_exposes_its_accelerator(self):
        self.assertEqual(MenuLabel("&File", id="menu_file").mnemonic, "f")

    def test_theme_change_restyles_the_menu_chrome(self):
        """The menu bar is composed once and stays mounted, so a theme switch
        has to re-render it or it keeps the old accelerator color."""
        app = _mock_app()
        label, dropdown = MagicMock(), MagicMock()
        app.query = MagicMock(
            side_effect=lambda widget_type: [label] if widget_type is MenuLabel else [dropdown]
        )
        with patch.object(
            GitNightCommanderApp, "theme", MIDNIGHT_COMMANDER_THEME_NAME, create=True
        ):
            app._restyle_menu_mnemonics()
        label.apply_mnemonic_style.assert_called_once()
        dropdown.apply_mnemonic_style.assert_called_once()


class TestStatusListItemClicks(unittest.TestCase):
    """Single click = highlight only; double click (or Enter) = open."""

    def _item(self, parent=None) -> StatusListItem:
        """Build a bare StatusListItem for unit testing.

        `__new__` skips MessagePump.__init__, which normally initializes the
        mangled `_MessagePump__parent` weakref slot. We set it directly so
        `self.parent` doesn't raise AttributeError.
        """
        item = StatusListItem.__new__(StatusListItem)
        item._MessagePump__parent = None if parent is None else (lambda: parent)  # type: ignore[attr-defined]
        return item

    def test_single_click_prevents_default_and_stops(self):
        """prevent_default is the load-bearing call: it short-circuits
        Textual's MRO dispatch so ListItem._on_click never runs and
        _ChildClicked is never posted. Without it, single clicks would
        still open files."""
        item = self._item()
        event = MagicMock()
        event.chain = 1
        item._on_click(event)
        event.prevent_default.assert_called_once_with()

    def test_single_click_focuses_list_and_moves_cursor(self):
        """Clicking highlights the row (like arrow-key navigation), so a
        subsequent arrow-up/down continues from the clicked row."""
        parent = MagicMock()
        item = self._item(parent=parent)
        parent.children = [MagicMock(), MagicMock(), item, MagicMock()]
        event = MagicMock()
        event.chain = 1
        item._on_click(event)
        parent.focus.assert_called_once_with()
        self.assertEqual(parent.index, 2)

    def test_single_click_without_parent_is_noop(self):
        """Defensive: if the item isn't mounted, skip the highlight step."""
        item = self._item()
        event = MagicMock()
        event.chain = 1
        item._on_click(event)  # must not raise

    def test_double_click_falls_through(self):
        item = self._item()
        event = MagicMock()
        event.chain = 2
        item._on_click(event)
        event.prevent_default.assert_not_called()
        event.stop.assert_not_called()

    def test_triple_click_falls_through(self):
        item = self._item()
        event = MagicMock()
        event.chain = 3
        item._on_click(event)
        event.prevent_default.assert_not_called()
        event.stop.assert_not_called()

    def test_defaults_to_single_click_when_chain_missing(self):
        """If somehow chain isn't set, treat as single click (safer default)."""
        item = self._item()

        class BareEvent:
            prevented = False
            stopped = False

            def prevent_default(self):
                self.prevented = True

            def stop(self):
                self.stopped = True

        event = BareEvent()
        item._on_click(event)
        self.assertTrue(event.prevented)
        self.assertTrue(event.stopped)


class TestMultiSelection(unittest.TestCase):
    """SHIFT+arrow / SHIFT+click toggle multi-selection in GitFilelist."""

    def _make_app_with_two_files(self):
        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        return app, first, second

    def test_shift_down_toggles_current_row_and_moves_cursor(self):
        app, first, _second = self._make_app_with_two_files()
        status_list = MagicMock()
        status_list.index = 0
        status_list.children = [MagicMock(), MagicMock()]
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._extend_status_selection(1)

        self.assertEqual(app.status_entries.selected_filenames, {first.filename})
        self.assertEqual(status_list.index, 1)

    def test_shift_up_at_first_row_selects_without_moving(self):
        app, first, _ = self._make_app_with_two_files()
        status_list = MagicMock()
        status_list.index = 0
        status_list.children = [MagicMock(), MagicMock()]
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._extend_status_selection(-1)

        self.assertEqual(app.status_entries.selected_filenames, {first.filename})
        self.assertEqual(status_list.index, 0)

    def test_shift_arrow_toggles_off_when_already_selected(self):
        app, _first, _ = self._make_app_with_two_files()
        app.status_entries.toggle_selection(0)
        status_list = MagicMock()
        status_list.index = 0
        status_list.children = [MagicMock(), MagicMock()]
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._extend_status_selection(1)

        self.assertEqual(app.status_entries.selected_filenames, set())

    def test_toggle_status_selection_updates_filelist(self):
        app, _, second = self._make_app_with_two_files()
        status_list = MagicMock()
        status_list.children = [MagicMock(), MagicMock()]
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._toggle_status_selection(1)

        self.assertEqual(app.status_entries.selected_filenames, {second.filename})

    def test_apply_selection_classes_marks_selected_items(self):
        app, _, _second = self._make_app_with_two_files()
        app.status_entries.toggle_selection(1)

        item0 = MagicMock()
        item1 = MagicMock()
        status_list = MagicMock()
        status_list.children = [item0, item1]
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._apply_selection_classes()

        item0.remove_class.assert_called_with("selected")
        item1.add_class.assert_called_with("selected")

    def test_mode_switch_preserves_selected_files(self):
        """Switching between short and long file list modes must not drop
        selections — they live on GitFilelist and must carry across the
        _load_status() reload."""
        app = _mock_app()
        app.file_list_mode = MODE_LONG
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        app.status_entries.toggle_selection(0)
        app.git.load_status.return_value = GitFilelist([first, second])

        status_view = MagicMock()
        status_list = MagicMock()
        status_list.index = 0
        status_list.children = [MagicMock(), MagicMock()]
        inline_diff = MagicMock()
        diff_full = MagicMock()
        switcher = MagicMock()
        switcher.current = "status-view"

        def query_one(selector, *args, **kwargs):
            if selector == "#status-view":
                return status_view
            if selector == "#status_list":
                return status_list
            if selector == "#file-diff":
                return inline_diff
            if selector == "#diff-full":
                return diff_full
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one
        app.action_short_file_list()

        self.assertEqual(app.status_entries.selected_filenames, {first.filename})

    def test_load_status_drops_selections_for_files_no_longer_present(self):
        app = _mock_app()
        gone = GitEntry(GitCode.MODIFIED_UNMODIFIED, "gone.py")
        keeps = GitEntry(GitCode.MODIFIED_UNMODIFIED, "keeps.py")
        app.status_entries = GitFilelist([gone, keeps])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)
        app.git.load_status.return_value = GitFilelist([keeps])

        app._load_status()

        self.assertEqual(app.status_entries.selected_filenames, {"keeps.py"})


class TestCtrlClickSelection(unittest.TestCase):
    """CTRL + single mouse click toggles a file in the multi-selection.

    We use CTRL rather than SHIFT because most terminals (VS Code, iTerm2,
    Terminal.app, xterm) intercept SHIFT+click for native text selection and
    never forward it to Textual. CTRL+click is forwarded reliably."""

    def _item(self, parent=None) -> StatusListItem:
        item = StatusListItem.__new__(StatusListItem)
        item._MessagePump__parent = None if parent is None else (lambda: parent)  # type: ignore[attr-defined]
        return item

    def test_ctrl_click_delegates_to_app_toggle(self):
        parent = MagicMock()
        item = self._item(parent=parent)
        parent.children = [MagicMock(), item]
        app = MagicMock()
        # MagicMock.__class__ is MagicMock, but `self.app` comes via the
        # Textual `app` descriptor. Bypass that by setting directly.
        type(item).app = property(lambda self: app)  # type: ignore[attr-defined]
        try:
            event = MagicMock()
            event.ctrl = True
            event.chain = 1

            item._on_click(event)

            event.prevent_default.assert_called_once_with()
            app._toggle_status_selection.assert_called_once_with(1)
            # Ctrl-click must NOT move the cursor/highlight.
            parent.focus.assert_not_called()
        finally:
            del type(item).app

    def test_plain_click_with_magicmock_ctrl_attribute_is_not_triggered(self):
        """Safety net: MagicMock auto-attributes are truthy but not True.
        Using `is True` in the handler prevents ctrl-branch leakage in
        existing single-click tests that don't set event.ctrl explicitly."""
        parent = MagicMock()
        item = self._item(parent=parent)
        parent.children = [item]
        event = MagicMock()
        event.chain = 1
        # event.ctrl is auto-MagicMock, which is truthy but not True.

        item._on_click(event)

        # Falls through to the normal single-click highlight path.
        parent.focus.assert_called_once_with()


class TestSpaceKeyToggle(unittest.TestCase):
    """Space toggles selection on the current row (no cursor movement)."""

    def test_toggle_current_status_selection_flips_current_row(self):
        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])

        status_list = MagicMock()
        status_list.index = 1
        status_list.children = [MagicMock(), MagicMock()]
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._toggle_current_status_selection()

        self.assertEqual(app.status_entries.selected_filenames, {second.filename})
        # Cursor must NOT move.
        self.assertEqual(status_list.index, 1)

    def test_toggle_current_status_selection_noop_when_no_highlight(self):
        app = _mock_app()
        app.status_entries = GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "a.py")])
        status_list = MagicMock()
        status_list.index = None
        status_list.children = [MagicMock()]
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._toggle_current_status_selection()

        self.assertEqual(app.status_entries.selected_filenames, set())

    def test_clear_selection_empties_selected_filenames_in_status_view(self):
        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        item0 = MagicMock()
        item1 = MagicMock()
        status_list = MagicMock()
        status_list.children = [item0, item1]
        switcher = MagicMock()
        switcher.current = "status-view"

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one

        app.action_clear_selection()

        self.assertEqual(app.status_entries.selected_filenames, set())
        item0.remove_class.assert_called_with("selected")
        item1.remove_class.assert_called_with("selected")

    def test_clear_selection_is_noop_outside_status_view(self):
        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        app.status_entries = GitFilelist([first])
        app.status_entries.toggle_selection(0)

        switcher = MagicMock()
        switcher.current = "history-view"

        def query_one(selector, *args, **kwargs):
            if isinstance(selector, type):
                return switcher
            return MagicMock()

        app.query_one.side_effect = query_one

        app.action_clear_selection()

        self.assertEqual(app.status_entries.selected_filenames, {first.filename})

    def test_clear_selection_is_noop_while_confirm_dialog_open(self):
        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        app.status_entries = GitFilelist([first])
        app.status_entries.toggle_selection(0)
        app._pending_confirm = lambda: None

        app.action_clear_selection()

        self.assertEqual(app.status_entries.selected_filenames, {first.filename})


class TestUIThemeCssVariables(unittest.TestCase):
    """CSS variables a UITheme contributes must contain concrete colors,
    not unresolved ``$primary`` / ``$warning`` / … references.

    Why: Textual's CSS parser does a single-pass variable substitution. If
    we set ``cursor-row-background`` to the literal string ``$primary``,
    Textual replaces ``$cursor-row-background`` in CSS with ``$primary``
    and then fails to parse ``$primary`` as a color — the app aborts at
    start with "Invalid value ('$primary') for the background property".
    UITheme.css_variables() must resolve those refs before emitting them.
    """

    _SEMANTIC_FIELDS = (
        "menu-bar-background",
        "menu-bar-foreground",
        "footer-background",
        "footer-foreground",
        "cursor-row-background",
        "cursor-row-foreground",
        "selected-file-background",
        "selected-file-foreground",
        "selected-cursor-row-background",
        "selected-cursor-row-foreground",
    )

    def test_no_unresolved_theme_refs_in_css_variables(self):
        for ui_theme in THEMES:
            css_vars = ui_theme.css_variables()
            for field_name in self._SEMANTIC_FIELDS:
                value = css_vars[field_name]
                self.assertNotIn(
                    "$",
                    value,
                    msg=(
                        f"Theme {ui_theme.name!r} field {field_name!r} still "
                        f"contains an unresolved theme ref: {value!r}"
                    ),
                )

    def test_get_theme_propagates_resolved_css_variables(self):
        ui_theme = MIDNIGHT_COMMANDER_THEME
        theme = ui_theme.get_theme()
        variables = getattr(theme, "variables", None)
        if not isinstance(variables, dict):
            # Stub Theme in the test harness doesn't store variables; the
            # css_variables check above already covers the regression.
            self.skipTest("Theme stub does not expose variables")
        for field_name in self._SEMANTIC_FIELDS:
            self.assertNotIn("$", variables[field_name])


class TestChromeThemeColors(unittest.TestCase):
    """The menu bar and footer take their colors from the theme's chrome
    fields, not from a palette role.

    Why: ``background: $warning`` painted the bar in whatever "warning" means
    in the active theme — cyan under midnight-commander, yellow under nord,
    and a clash with Textual's own header/footer palette everywhere else.
    """

    def test_menu_bar_css_uses_chrome_variables(self):
        from gitnc.app import MenuBar

        self.assertIn("background: $menu-bar-background;", MenuBar.DEFAULT_CSS)
        self.assertIn("color: $menu-bar-foreground;", MenuBar.DEFAULT_CSS)
        self.assertNotIn("$warning", MenuBar.DEFAULT_CSS)

    def test_menu_label_states_derive_from_chrome_variables(self):
        from gitnc.app import MenuLabel

        self.assertNotIn("$warning", MenuLabel.DEFAULT_CSS)
        self.assertIn("background: $menu-bar-foreground 15%;", MenuLabel.DEFAULT_CSS)
        self.assertIn("background: $menu-bar-foreground;", MenuLabel.DEFAULT_CSS)

    def test_app_css_leaves_the_footer_to_textual(self):
        from gitnc.app import GitNightCommanderApp

        self.assertNotIn("Footer", GitNightCommanderApp.CSS)

    def test_chrome_defaults_match_textual_header_and_footer(self):
        from gitnc.ui_theme import UITheme

        theme = UITheme(name="plain", primary="#ffffff")

        self.assertEqual(theme.menu_bar_background, "$panel")
        self.assertEqual(theme.menu_bar_foreground, "$foreground")
        self.assertEqual(theme.footer_background, "$panel")
        self.assertEqual(theme.footer_foreground, "$foreground")

    def test_midnight_commander_keeps_its_colored_bars(self):
        css_vars = MIDNIGHT_COMMANDER_THEME.css_variables()

        self.assertEqual(css_vars["menu-bar-background"], MIDNIGHT_COMMANDER_THEME.warning)
        self.assertEqual(css_vars["menu-bar-foreground"], MIDNIGHT_COMMANDER_THEME.background)
        self.assertEqual(css_vars["footer-background"], MIDNIGHT_COMMANDER_THEME.warning)
        self.assertEqual(css_vars["footer-foreground"], MIDNIGHT_COMMANDER_THEME.background)


class TestSelectionStyling(unittest.TestCase):
    """Selected rows must get the `selected` CSS class for a distinct color."""

    def test_status_list_css_defines_selected_style(self):
        from gitnc.app import StatusList

        self.assertIn("StatusList ListItem.selected", StatusList.DEFAULT_CSS)

    def test_render_marks_selected_rows_with_selected_class(self):
        from gitnc.app import StatusListItem

        app = _mock_app()
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/second.py")
        app.status_entries = GitFilelist([first, second])
        app.status_entries.toggle_selection(1)

        appended: list[StatusListItem] = []
        status_list = MagicMock()
        status_list.append.side_effect = appended.append
        status_list.content_region = types.SimpleNamespace(width=120)
        app.query_one.side_effect = lambda sel, *a, **k: (
            status_list if sel == "#status_list" else MagicMock()
        )

        app._render_status_rows()

        self.assertEqual(len(appended), 2)
        # StatusListItem stub (Widget) stores `classes` via **kwargs — only
        # checked on the real class hierarchy. For this test we only need
        # to verify that the kwarg flows through to the append call.
        calls = status_list.append.call_args_list
        self.assertEqual(calls[0].args[0].__class__.__name__, "StatusListItem")


class TestCommitFlow(unittest.TestCase):
    """C commits the highlighted file or every selected file.

    Unstaged targets get a stage confirmation popup; staged files outside the
    selection are unstaged before the commit dialog opens and restored
    afterwards (or on cancel)."""

    def _app(
        self,
        entries,
        highlight_index: int | None = 0,
        *,
        staged: set[str] | frozenset[str] = frozenset(),
        branch=None,
    ):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist(entries)
        app.git.load_status.return_value = GitFilelist(entries)
        app.git.stage_command.side_effect = lambda f: ["git", "add", "--", f]
        app.git.unstage_command.side_effect = lambda f: [
            "git",
            "restore",
            "--staged",
            "--",
            f,
        ]
        app.git.stage_file.return_value = MagicMock(returncode=0, stderr="")
        app.git.unstage_file.return_value = MagicMock(returncode=0, stderr="")
        app.git.staged_filenames.return_value = set(staged)
        app.git.branch_name.return_value = branch
        app.git.commit.return_value = MagicMock(returncode=0, stderr="")

        dialogs = _DialogProbe(app)
        status_list = MagicMock()
        status_list.index = highlight_index

        def query_one(selector, *args, **kwargs):
            if selector == "#status_list":
                return status_list
            return MagicMock()

        app.query_one.side_effect = query_one
        return app, dialogs, status_list

    def _commit_screen(self, dialogs) -> Any:
        """The CommitDialog the app pushed, failing loudly if it didn't."""
        pushed = [s for s in dialogs.pushed if isinstance(s, CommitDialog)]
        self.assertEqual(len(pushed), 1, f"expected one CommitDialog, got {dialogs.pushed}")
        return pushed[0]

    def _assert_no_commit_dialog(self, dialogs) -> None:
        self.assertEqual([s for s in dialogs.pushed if isinstance(s, CommitDialog)], [])

    def _assert_no_confirm(self, dialogs) -> None:
        self.assertEqual([s for s in dialogs.pushed if isinstance(s, ConfirmDialog)], [])

    def test_commit_on_staged_file_skips_stage_confirmation(self):
        """A file that's already fully staged opens the commit dialog straight
        away (no stage prompt needed)."""
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py"})

        app.action_commit_files()

        self._assert_no_confirm(dialogs)
        self.assertEqual(self._commit_screen(dialogs).prefill, "")
        app.git.commit.assert_not_called()

    def test_commit_on_unstaged_file_shows_stage_confirmation_first(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry])

        app.action_commit_files()

        dialogs.assert_confirm("Stage 1 file(s) for commit?", ["git add -- pkg/a.py"])
        self._assert_no_commit_dialog(dialogs)
        app.git.stage_file.assert_not_called()

    def test_confirming_stage_then_opens_commit_dialog(self):
        """Y on the stage confirmation runs `git add` for the unstaged target
        and then opens the commit message dialog."""
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry])
        app.action_commit_files()

        dialogs.confirm()

        app.git.stage_file.assert_called_once_with("pkg/a.py")
        self.assertEqual(self._commit_screen(dialogs).prefill, "")

    def test_externally_staged_files_are_unstaged_before_commit_dialog(self):
        """Files currently staged but not in the commit target must be
        unstaged before the commit dialog opens, so `git commit` only picks
        up the intended files."""
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/target.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/target.py", "other/a.py", "other/b.py"})

        app.action_commit_files()

        # Only "other/a.py" and "other/b.py" get unstaged (targets are kept).
        self.assertEqual(
            sorted(c.args for c in app.git.unstage_file.call_args_list),
            [("other/a.py",), ("other/b.py",)],
        )
        self.assertEqual(self._commit_screen(dialogs).prefill, "")
        self.assertEqual(app._pending_commit_externals, ["other/a.py", "other/b.py"])

    def test_commit_dialog_prefills_branch_name_when_setting_enabled(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py"}, branch="feature/foo")
        with patch.object(
            app,
            "_load_settings",
            return_value={"branch_prefix_in_commits": True},
        ):
            app.action_commit_files()

        self.assertEqual(self._commit_screen(dialogs).prefill, "feature/foo: ")

    def test_commit_dialog_does_not_prefill_when_setting_disabled(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py"}, branch="feature/foo")
        with patch.object(
            app,
            "_load_settings",
            return_value={"branch_prefix_in_commits": False},
        ):
            app.action_commit_files()

        self.assertEqual(self._commit_screen(dialogs).prefill, "")

    def test_submitting_commit_runs_git_commit_and_restages_externals(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py", "other/b.py"})
        app.action_commit_files()

        app.git.stage_file.reset_mock()
        dialogs._resolve("feat: something")
        dialogs.confirm()

        app.git.commit.assert_called_once_with("feat: something")
        # External was re-staged after the commit.
        app.git.stage_file.assert_called_once_with("other/b.py")
        self.assertEqual(app._pending_commit_externals, [])

    def test_cancelling_commit_restages_externals_without_committing(self):
        """The dialog dismisses with None on Esc, which must restore the
        externals we unstaged on the way in."""
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py", "other/b.py"})
        app.action_commit_files()

        app.git.stage_file.reset_mock()
        dialogs._resolve(None)

        app.git.commit.assert_not_called()
        app.git.stage_file.assert_called_once_with("other/b.py")
        self.assertEqual(app._pending_commit_externals, [])

    def test_cancelling_commit_unstages_what_the_flow_staged(self):
        """Esc must undo the `git add` the stage confirmation ran, or the file
        stays staged and a second C never asks to stage it again."""
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry])
        app.action_commit_files()
        dialogs.confirm()  # Y on "Stage 1 file(s) for commit?"
        self.assertEqual(app._pending_commit_staged, [entry])

        dialogs._resolve(None)

        app.git.commit.assert_not_called()
        app.git.unstage_file.assert_called_once_with("pkg/a.py")
        self.assertEqual(app._pending_commit_staged, [])

    def test_stage_confirmation_returns_after_a_cancelled_commit(self):
        """The whole point of the rollback: C after a cancelled C asks the
        same question it asked the first time.

        The index is modelled here (staging flips the entry's status letters,
        and the reload picks that up), so the second C sees what git would
        have told it rather than the first call's stale entry.
        """
        staged: set[str] = set()
        app, dialogs, _ = self._app([GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")])
        app.git.stage_file.side_effect = staged.add
        app.git.unstage_file.side_effect = staged.discard
        app.git.staged_filenames.side_effect = lambda: set(staged)
        app.git.load_status.side_effect = lambda: GitFilelist(
            [
                GitEntry(
                    GitCode.MODIFIED_UNMODIFIED
                    if "pkg/a.py" in staged
                    else GitCode.UNMODIFIED_MODIFIED,
                    "pkg/a.py",
                )
            ]
        )

        app.action_commit_files()
        dialogs.confirm()
        self.assertEqual(staged, {"pkg/a.py"})
        dialogs._resolve(None)
        self.assertEqual(staged, set())
        dialogs.reset()

        app.action_commit_files()

        dialogs.assert_confirm("Stage 1 file(s) for commit?", ["git add -- pkg/a.py"])

    def test_cancelling_commit_keeps_a_partially_staged_file_staged(self):
        """A file that already had staged changes was staged *partially*;
        `git restore --staged` would drop that work, so the rollback leaves
        it alone."""
        entry = GitEntry(GitCode.MODIFIED_MODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py"})
        app.action_commit_files()
        dialogs.confirm()
        app.git.unstage_file.reset_mock()

        dialogs._resolve(None)

        self.assertEqual(app._pending_commit_staged, [])
        app.git.unstage_file.assert_not_called()

    def test_committing_does_not_unstage_the_files_it_committed(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry])
        app.action_commit_files()
        dialogs.confirm()
        app.git.unstage_file.reset_mock()

        dialogs._resolve("feat: something")
        dialogs.confirm()

        app.git.commit.assert_called_once_with("feat: something")
        app.git.unstage_file.assert_not_called()
        self.assertEqual(app._pending_commit_staged, [])

    def test_escape_in_commit_dialog_dismisses_with_none(self):
        """Esc is the dialog's own key: CommitTextArea's binding routes to the
        screen, which dismisses with None rather than a message."""
        dialog = CommitDialog(prefill="")
        with patch.object(CommitDialog, "dismiss") as dismiss:
            dialog.cancel()

        dismiss.assert_called_once_with(None)

    def test_empty_commit_message_notifies_and_does_not_dismiss(self):
        """F2 on a blank message keeps the dialog open instead of committing."""
        dialog = CommitDialog(prefill="")
        with (
            patch.object(CommitDialog, "dismiss") as dismiss,
            patch.object(CommitDialog, "get_text", return_value="   \n  "),
            patch.object(CommitDialog, "app", new_callable=PropertyMock) as app_prop,
        ):
            dialog.submit()

        dismiss.assert_not_called()
        app_prop.return_value.notify.assert_called_with("Commit message cannot be empty")

    def test_f2_dismisses_with_the_stripped_message(self):
        dialog = CommitDialog(prefill="")
        with (
            patch.object(CommitDialog, "dismiss") as dismiss,
            patch.object(CommitDialog, "get_text", return_value="  feat: x  \n"),
        ):
            dialog.submit()

        dismiss.assert_called_once_with("feat: x")

    def test_commit_text_area_peels_off_only_f2_and_escape(self):
        """The TextArea owns every other key so the user can type freely."""
        bindings = {b.key: b.action for b in CommitTextArea.BINDINGS}

        self.assertEqual(bindings["f2"], "commit_submit")
        self.assertEqual(bindings["escape"], "commit_cancel")

    def test_commit_text_area_actions_delegate_to_the_screen(self):
        """Delegation goes to the owning screen now, not the app."""
        text_area = MagicMock()

        CommitTextArea.action_commit_submit(text_area)
        CommitTextArea.action_commit_cancel(text_area)

        self.assertEqual(
            [c.args for c in text_area._dialog_action.call_args_list],
            [("submit",), ("cancel",)],
        )

    def test_dialog_action_calls_the_named_handler_on_the_screen(self):
        text_area = MagicMock()
        screen = MagicMock()
        type(text_area).screen = PropertyMock(return_value=screen)

        CommitTextArea._dialog_action(text_area, "submit")

        screen.submit.assert_called_once_with()

    def test_commit_with_multiple_selected_files(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/b.py")
        app, dialogs, _ = self._app([a, b], staged={"pkg/a.py"})
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_commit_files()

        dialogs.assert_confirm("Stage 1 file(s) for commit?", ["git add -- pkg/b.py"])

    def test_commit_with_no_highlight_or_selection_notifies(self):
        a = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([a], highlight_index=None)
        with patch.object(app, "notify") as notify:
            app.action_commit_files()
        dialogs.assert_not_shown()
        notify.assert_called_once_with("Nothing to commit")

    def test_commit_failure_surfaces_stderr_in_notification(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py"})
        app.git.commit.return_value = MagicMock(returncode=1, stderr="nothing to commit\n")
        app.action_commit_files()

        with patch.object(app, "notify") as notify:
            dialogs._resolve("feat: x")
            dialogs.confirm()

        notify.assert_called_with("git commit failed: nothing to commit")

    def test_submitting_the_message_asks_before_committing(self):
        """The last look at what is going into the commit: the message dialog
        hands over to a confirmation listing the commands that will run."""
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py"})
        app.action_commit_files()

        dialogs._resolve("feat: x")

        self.assertEqual(dialogs.prompt(), "Commit 1 file(s)?")
        self.assertEqual(dialogs.commands(), ["git commit -m feat: x"])
        app.git.commit.assert_not_called()

    def test_the_confirmation_shows_only_the_subject_of_a_long_message(self):
        """The popup renders one command per row, so a multi-line `-m` has to
        be cut down to its first line — marked as cut."""
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py"})
        app.action_commit_files()

        dialogs._resolve("feat: x\n\nthe body\n")

        self.assertEqual(dialogs.commands(), [f"git commit -m feat: x{TRUNCATION_MARKER}"])
        # The commit itself still gets the whole message.
        dialogs.confirm()
        app.git.commit.assert_called_once_with("feat: x\n\nthe body\n")

    def test_declining_the_confirmation_reopens_the_message_dialog(self):
        """N goes back to the message rather than throwing it away, and
        nothing is committed or re-staged in the meantime."""
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        app, dialogs, _ = self._app([entry], staged={"pkg/a.py", "other/b.py"})
        app.action_commit_files()

        app.git.stage_file.reset_mock()
        dialogs._resolve("feat: x")
        dialogs.cancel()

        reopened = [s for s in dialogs.pushed if isinstance(s, CommitDialog)][-1]
        self.assertEqual(reopened.prefill, "feat: x")
        app.git.commit.assert_not_called()
        app.git.stage_file.assert_not_called()
        self.assertEqual(app._pending_commit_externals, ["other/b.py"])


class _FakeProcess:
    """Stand-in for the `Popen` the drafting tool runs in.

    `StringIO` is enough of a pipe for the pumps: it iterates by line and
    closes under `with`. `waited` records whether the process has been reaped
    yet, which is how the streaming test tells "reported while running" from
    "reported at the end".
    """

    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.waited = False
        self.killed = False

    def wait(self) -> int:
        self.waited = True
        return self.returncode

    def kill(self) -> None:
        self.killed = True


class _HangingProcess:
    """A tool that prints nothing and never exits, until it is killed.

    It stands in for its own stdout: iterating blocks, which is exactly the
    state the timeout exists for.
    """

    def __init__(self) -> None:
        self.stdout = self
        self.stderr = io.StringIO("")
        self.returncode = -9
        self.killed = False
        self._released = threading.Event()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def __iter__(self):
        self._released.wait(timeout=5)
        return iter(())

    def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self._released.set()


class _Suspension:
    """Stand-in for `App.suspend()`, which needs a running driver.

    Calling it returns itself, so `app.suspend = _Suspension()` behaves like
    the bound method. `active` says whether the app is suspended right now,
    which is how the tests tell that the tool ran on the previous screen
    rather than under the TUI. `supported=False` is the terminal that can't
    be suspended: real Textual raises from the `with`, not from the call.
    """

    def __init__(self, *, supported: bool = True) -> None:
        self.supported = supported
        self.entered = 0
        self.active = False

    def __call__(self) -> Self:
        return self

    def __enter__(self) -> None:
        if not self.supported:
            raise SuspendNotSupported("no driver to suspend")
        self.entered += 1
        self.active = True

    def __exit__(self, *exc_info: object) -> bool:
        self.active = False
        return False


class TestCommitDraft(unittest.TestCase):
    """Drafting a commit message: the Draft button runs the tool named in the
    settings on the previous screen, and drops what it prints into the (still
    editable) text area."""

    def _dialog(self) -> Any:
        """A stand-in for the open CommitDialog the app is drafting into."""
        return MagicMock(spec=CommitDialog)

    def _app(self, settings: dict[str, Any], *, branch: str | None = None) -> Any:
        app = _mock_app()
        app._pending_commit_targets = [GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")]
        app._load_settings = MagicMock(return_value=settings)
        app.git.branch_name.return_value = branch
        app.notify = MagicMock()
        # The drafting run suspends the app and writes to the terminal it was
        # started from; neither is available to a test, and an unmocked
        # Terminal would print the fake tool's output over the test run.
        app.suspend = _Suspension()
        app._screen = MagicMock()
        return app

    def _written(self, app: Any) -> list[str]:
        """Everything the app put on the previous screen, in order."""
        return [call.args[0] for call in app._screen.write_previous_screen.call_args_list]

    def test_prompt_is_the_template_followed_by_the_files(self):
        self.assertEqual(
            commit_draft_prompt("Write a message for:", ["pkg/a.py", "pkg/b.py"]),
            "Write a message for:\npkg/a.py\npkg/b.py",
        )

    def test_the_tool_gets_the_prompt_as_its_last_argument(self):
        """`<command as typed> <prompt + files>`: the command line is split
        the way a shell would, and the prompt stays one argument."""
        process = _FakeProcess(stdout="feat: add a thing\n")
        with patch("gitnc.app.subprocess.Popen", return_value=process) as popen:
            drafted = run_commit_draft(
                argv=["claude", "-p"], prompt="Write a message for:\npkg/a.py", cwd="/repo"
            )

        self.assertEqual(
            popen.call_args.args[0],
            ["claude", "-p", "Write a message for:\npkg/a.py"],
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], "/repo")
        # A tool that decides to prompt would otherwise fight the TUI for the
        # terminal and hang the worker.
        self.assertEqual(popen.call_args.kwargs["stdin"], _app_module.subprocess.DEVNULL)
        self.assertEqual(drafted, DraftResult(ok=True, text="feat: add a thing"))

    def test_output_is_reported_line_by_line_while_the_tool_runs(self):
        """The point of the whole Popen dance: the caller sees each line as
        it is printed, not once the process has exited."""
        process = _FakeProcess(stdout="step one\nfeat: x\n", stderr="thinking\n")
        seen: list[tuple[str, bool]] = []
        with patch("gitnc.app.subprocess.Popen", return_value=process):
            drafted = run_commit_draft(
                argv=["tool"],
                prompt="p",
                cwd=".",
                on_output=lambda line: seen.append((line, process.waited)),
            )

        self.assertEqual(sorted(line for line, _ in seen), ["feat: x", "step one", "thinking"])
        # Every line arrived before the process was reaped.
        self.assertEqual([waited for _, waited in seen], [False, False, False])
        # stderr is progress, not part of the message.
        self.assertEqual(drafted, DraftResult(ok=True, text="step one\nfeat: x"))

    def test_colour_escapes_in_the_output_are_stripped(self):
        process = _FakeProcess(stdout="\x1b[32mfeat: x\x1b[0m\n")
        with patch("gitnc.app.subprocess.Popen", return_value=process):
            drafted = run_commit_draft(argv=["tool"], prompt="p", cwd=".")

        self.assertEqual(drafted, DraftResult(ok=True, text="feat: x"))

    def test_a_failing_tool_reports_its_last_stderr_line(self):
        process = _FakeProcess(returncode=2, stderr="usage: tool\nno such flag\n")
        with patch("gitnc.app.subprocess.Popen", return_value=process):
            drafted = run_commit_draft(argv=["tool"], prompt="p", cwd=".")

        self.assertEqual(drafted, DraftResult(ok=False, text="tool failed: no such flag"))

    def test_a_missing_tool_is_reported_rather_than_raised(self):
        with patch("gitnc.app.subprocess.Popen", side_effect=FileNotFoundError("tool")):
            drafted = run_commit_draft(argv=["tool"], prompt="p", cwd=".")

        self.assertFalse(drafted.ok)
        self.assertIn("Could not run tool", drafted.text)

    def test_a_hung_tool_is_killed_and_reported_as_timed_out(self):
        """No output ever comes, so the pump would block forever; the
        watchdog kills the process and that ends it."""
        process = _HangingProcess()
        with (
            patch("gitnc.app.subprocess.Popen", return_value=process),
            patch("gitnc.app.COMMIT_DRAFT_TIMEOUT_SECONDS", 0.05),
        ):
            drafted = run_commit_draft(argv=["tool"], prompt="p", cwd=".")

        self.assertTrue(process.killed)
        self.assertFalse(drafted.ok)
        self.assertIn("timed out", drafted.text)

    def test_ctrl_c_on_the_previous_screen_kills_the_tool_and_reports_it(self):
        """The app is suspended, so the terminal is in cooked mode and the
        interrupt lands in the pump. Letting it escape would skip
        `App.suspend()`'s resume and strand the terminal outside the
        alternate screen."""
        process = _FakeProcess(stdout="feat: x\n")

        def pump(*, stream, sink, on_output):
            """Ctrl+C arrives in the pump the caller is blocked in — the
            stdout one; the stderr reader is on its own thread."""
            if stream is process.stdout:
                raise KeyboardInterrupt

        with (
            patch("gitnc.app.subprocess.Popen", return_value=process),
            patch("gitnc.app._pump_draft_output", side_effect=pump),
        ):
            drafted = run_commit_draft(argv=["tool"], prompt="p", cwd=".")

        self.assertTrue(process.killed)
        self.assertEqual(drafted, DraftResult(ok=False, text="tool cancelled"))

    def test_silent_tool_is_reported_rather_than_emptying_the_message(self):
        process = _FakeProcess(stdout="  \n")
        with patch("gitnc.app.subprocess.Popen", return_value=process):
            drafted = run_commit_draft(argv=["tool"], prompt="p", cwd=".")

        self.assertFalse(drafted.ok)

    def test_no_configured_command_says_so_and_runs_nothing(self):
        app = self._app({})
        dialog = self._dialog()

        with patch("gitnc.app.run_commit_draft") as run:
            app.request_commit_draft(dialog)

        run.assert_not_called()
        dialog.set_drafting.assert_not_called()
        app.notify.assert_called_once_with("No commit message tool configured (Options → Settings)")

    def test_an_unparseable_command_is_reported(self):
        app = self._app({"commit_draft_command": 'claude -p "'})
        dialog = self._dialog()

        with patch("gitnc.app.run_commit_draft") as run:
            app.request_commit_draft(dialog)

        run.assert_not_called()
        self.assertIn("Could not read", app.notify.call_args.args[0])

    def test_drafting_runs_the_tool_and_fills_the_text_area(self):
        app = self._app(
            {"commit_draft_command": "claude -p", "commit_draft_prompt": "Write a message for:"}
        )
        dialog = self._dialog()

        with patch(
            "gitnc.app.run_commit_draft",
            return_value=DraftResult(ok=True, text="feat: add a thing"),
        ) as run:
            app.request_commit_draft(dialog)

        self.assertEqual(run.call_args.kwargs["argv"], ["claude", "-p"])
        self.assertEqual(run.call_args.kwargs["prompt"], "Write a message for:\npkg/a.py")
        dialog.set_text.assert_called_once_with("feat: add a thing")
        # The button unlocks whatever the tool did.
        self.assertEqual([c.args for c in dialog.set_drafting.call_args_list], [(True,), (False,)])

    def test_the_output_shown_on_the_screen_is_not_repeated_in_the_dialog(self):
        """The user has just watched the whole run; showing it again under
        the message box would bury the one thing the dialog is for."""
        app = self._app({"commit_draft_command": "tool"})
        dialog = self._dialog()

        with patch("gitnc.app.run_commit_draft", side_effect=self._streaming()):
            app.request_commit_draft(dialog)

        dialog.append_output.assert_not_called()
        dialog.set_text.assert_called_once_with("feat: x")

    def _streaming(self, *, text: str = "feat: x") -> Callable[..., Any]:
        """A tool that prints two lines before answering with `text`."""

        def stream(**kwargs):
            kwargs["on_output"]("step one")
            kwargs["on_output"]("step two")
            return DraftResult(ok=True, text=text)

        return stream

    def test_the_tool_runs_on_the_previous_screen(self):
        """F4 goes where Ctrl+O goes: the app is suspended for the length of
        the run, so the tool's output lands on the terminal the TUI was
        started from and stays in its scrollback afterwards."""
        app = self._app({"commit_draft_command": "tool"})
        suspended: list[bool] = []

        def run(**kwargs):
            suspended.append(app.suspend.active)
            kwargs["on_output"]("step one")
            return DraftResult(ok=True, text="feat: x")

        with patch("gitnc.app.run_commit_draft", side_effect=run):
            app.request_commit_draft(self._dialog())

        self.assertEqual(suspended, [True])
        self.assertEqual(app.suspend.entered, 1)
        # ...and the TUI is back before anything is rendered into it.
        self.assertFalse(app.suspend.active)

    def test_the_command_line_and_its_output_are_shown_on_that_screen(self):
        app = self._app({"commit_draft_command": "tool -p", "commit_draft_prompt": "Draft:"})

        with patch("gitnc.app.run_commit_draft", side_effect=self._streaming()):
            app.request_commit_draft(self._dialog())

        written = self._written(app)
        # The command as a shell would show it, so the scrollback says what
        # ran and not only what it printed.
        self.assertEqual(written[0], "$ tool -p 'Draft:\npkg/a.py'\n")
        self.assertEqual(written[1:3], ["step one\n", "step two\n"])

    def test_output_reaches_the_screen_while_the_tool_is_still_running(self):
        app = self._app({"commit_draft_command": "tool"})
        seen: list[list[str]] = []

        def run(**kwargs):
            kwargs["on_output"]("step one")
            seen.append(self._written(app))
            return DraftResult(ok=True, text="feat: x")

        with patch("gitnc.app.run_commit_draft", side_effect=run):
            app.request_commit_draft(self._dialog())

        self.assertIn("step one\n", seen[0])

    def test_a_terminal_that_cannot_be_suspended_drafts_under_the_tui(self):
        """No previous screen to run on, so the worker runs the same tool
        with the dialog's log as the only place its output shows."""
        app = self._app({"commit_draft_command": "tool"})
        app.suspend = _Suspension(supported=False)
        dialog = self._dialog()

        with patch("gitnc.app.run_commit_draft", side_effect=self._streaming()) as run:
            app.request_commit_draft(dialog)

        # Once: a failure to suspend must not send the tool off to a second run.
        run.assert_called_once()
        self.assertEqual(self._written(app), [])
        self.assertEqual(
            [c.args for c in dialog.append_output.call_args_list],
            [("step one",), ("step two",)],
        )
        dialog.set_text.assert_called_once_with("feat: x")

    def _drafted(self, app: Any, dialog: Any, text: str) -> None:
        """Run the tool and let it answer with `text`."""
        with patch("gitnc.app.run_commit_draft", return_value=DraftResult(ok=True, text=text)):
            app.request_commit_draft(dialog)

    def _picker(self, app: Any) -> Any:
        pushed = [c.args[0] for c in app.push_screen.call_args_list]
        screens = [s for s in pushed if isinstance(s, SuggestionDialog)]
        self.assertEqual(len(screens), 1, f"expected one SuggestionDialog, got {pushed}")
        return screens[0]

    def test_a_numbered_list_opens_the_picker_when_the_setting_is_on(self):
        app = self._app({"commit_draft_command": "tool", "commit_draft_parse_suggestions": True})
        dialog = self._dialog()

        self._drafted(app, dialog, "Options:\n1. feat: one\n2. feat: two\n")

        self.assertEqual(self._picker(app).suggestions, ["feat: one", "feat: two"])
        # Nothing lands in the text area until the user has picked.
        dialog.set_text.assert_not_called()

    def test_picking_a_suggestion_fills_the_message(self):
        app = self._app({"commit_draft_command": "tool", "commit_draft_parse_suggestions": True})
        dialog = self._dialog()
        self._drafted(app, dialog, "1. feat: one\n2. feat: two\n")

        app.push_screen.call_args.kwargs["callback"]("feat: two")

        dialog.set_text.assert_called_once_with("feat: two")

    def test_cancelling_the_picker_leaves_the_message_alone(self):
        app = self._app({"commit_draft_command": "tool", "commit_draft_parse_suggestions": True})
        dialog = self._dialog()
        self._drafted(app, dialog, "1. feat: one\n2. feat: two\n")

        app.push_screen.call_args.kwargs["callback"](None)

        dialog.set_text.assert_not_called()

    def test_a_picked_suggestion_gets_the_branch_prefix_too(self):
        """The tool knows nothing about the setting, so the prefix is put on
        whichever of its suggestions the user took."""
        app = self._app(
            {"commit_draft_command": "tool", "commit_draft_parse_suggestions": True},
            branch="feature/foo",
        )
        app._load_settings = MagicMock(
            return_value={
                "commit_draft_command": "tool",
                "commit_draft_parse_suggestions": True,
                "branch_prefix_in_commits": True,
            }
        )
        dialog = self._dialog()
        self._drafted(app, dialog, "1. feat: one\n2. feat: two\n")

        app.push_screen.call_args.kwargs["callback"]("feat: two")

        dialog.set_text.assert_called_once_with("feature/foo: feat: two")

    def test_a_single_suggestion_skips_the_picker(self):
        """There is nothing to choose between — but the number still comes
        off, which is the point of the setting."""
        app = self._app({"commit_draft_command": "tool", "commit_draft_parse_suggestions": True})
        dialog = self._dialog()

        self._drafted(app, dialog, "1. feat: only one\n")

        app.push_screen.assert_not_called()
        dialog.set_text.assert_called_once_with("feat: only one")

    def test_output_with_no_list_falls_back_to_the_whole_thing(self):
        """A tool that ignored the request still wrote something; dropping it
        would be worse than handing it over."""
        app = self._app({"commit_draft_command": "tool", "commit_draft_parse_suggestions": True})
        dialog = self._dialog()

        self._drafted(app, dialog, "feat: just the one message")

        app.push_screen.assert_not_called()
        dialog.set_text.assert_called_once_with("feat: just the one message")
        self.assertIn("No numbered suggestions", app.notify.call_args.args[0])

    def test_a_numbered_list_goes_in_whole_when_the_setting_is_off(self):
        app = self._app({"commit_draft_command": "tool"})
        dialog = self._dialog()

        self._drafted(app, dialog, "1. feat: one\n2. feat: two")

        app.push_screen.assert_not_called()
        dialog.set_text.assert_called_once_with("1. feat: one\n2. feat: two")

    def test_output_from_a_run_that_outlived_the_app_is_dropped(self):
        """`call_from_thread` raises once the app has stopped; a line arriving
        then has nowhere to go, and losing it is the whole recovery."""
        app = self._app({"commit_draft_command": "tool"})
        app.call_from_thread = MagicMock(side_effect=RuntimeError("app is not running"))

        app._post_draft_output(dialog=self._dialog(), line="late")

    def test_the_default_prompt_is_used_when_none_was_configured(self):
        app = self._app({"commit_draft_command": "tool"})
        with patch(
            "gitnc.app.run_commit_draft", return_value=DraftResult(ok=True, text="x")
        ) as run:
            app.request_commit_draft(self._dialog())

        self.assertTrue(run.call_args.kwargs["prompt"].startswith(COMMIT_DRAFT_PROMPT_DEFAULT))

    def test_a_failed_draft_notifies_and_leaves_the_message_alone(self):
        app = self._app({"commit_draft_command": "tool"})
        dialog = self._dialog()

        with patch(
            "gitnc.app.run_commit_draft", return_value=DraftResult(ok=False, text="tool failed")
        ):
            app.request_commit_draft(dialog)

        dialog.set_text.assert_not_called()
        dialog.set_drafting.assert_called_with(False)
        app.notify.assert_called_once_with("tool failed")

    def test_branch_prefix_is_inserted_into_a_drafted_message(self):
        """The tool knows nothing about the setting, so a message that
        doesn't already carry the branch name gets it here."""
        app = self._app(
            {"commit_draft_command": "tool", "branch_prefix_in_commits": True},
            branch="feature/foo",
        )
        dialog = self._dialog()

        with patch("gitnc.app.run_commit_draft", return_value=DraftResult(ok=True, text="feat: x")):
            app.request_commit_draft(dialog)

        dialog.set_text.assert_called_once_with("feature/foo: feat: x")

    def test_a_message_already_prefixed_is_left_as_it_is(self):
        app = self._app(
            {"commit_draft_command": "tool", "branch_prefix_in_commits": True},
            branch="feature/foo",
        )
        dialog = self._dialog()

        with patch(
            "gitnc.app.run_commit_draft",
            return_value=DraftResult(ok=True, text="feature/foo: feat: x"),
        ):
            app.request_commit_draft(dialog)

        dialog.set_text.assert_called_once_with("feature/foo: feat: x")

    def test_no_prefix_is_added_when_the_setting_is_off(self):
        app = self._app({"commit_draft_command": "tool"}, branch="feature/foo")
        dialog = self._dialog()

        with patch("gitnc.app.run_commit_draft", return_value=DraftResult(ok=True, text="feat: x")):
            app.request_commit_draft(dialog)

        dialog.set_text.assert_called_once_with("feat: x")

    def test_f4_reaches_the_dialog_from_the_text_area(self):
        bindings = {b.key: b.action for b in CommitTextArea.BINDINGS}
        self.assertEqual(bindings["f4"], "commit_draft")

        text_area = MagicMock()
        CommitTextArea.action_commit_draft(text_area)
        text_area._dialog_action.assert_called_once_with("draft")

    def test_the_dialog_binds_the_same_keys_for_the_button(self):
        """With focus on the Draft button the TextArea's bindings are out of
        the chain, so the screen carries its own copy."""
        bindings = {b.key: b.action for b in CommitDialog.BINDINGS}

        self.assertEqual(
            bindings, {"f2": "commit_submit", "f4": "commit_draft", "escape": "commit_cancel"}
        )

    def test_draft_asks_the_app_to_run_the_tool(self):
        dialog = CommitDialog(prefill="")
        with patch.object(CommitDialog, "app", new_callable=PropertyMock) as app_prop:
            app = MagicMock()
            app_prop.return_value = app
            dialog.draft()

        app.request_commit_draft.assert_called_once_with(dialog)

    def test_pressing_the_draft_button_drafts(self):
        dialog = CommitDialog(prefill="")
        event = MagicMock()
        event.button.id = "commit-draft"

        with patch.object(CommitDialog, "draft") as draft:
            dialog.on_button_pressed(event)

        draft.assert_called_once_with()
        event.stop.assert_called_once_with()


class TestNumberedSuggestions(unittest.TestCase):
    """Reading a drafting tool's numbered list back into separate messages."""

    def test_the_numbers_and_the_chatter_around_them_are_dropped(self):
        text = (
            "Here are three options:\n"
            "1. feat: add the widget\n"
            "2) fix: stop the widget crashing\n"
            "3: chore: tidy the widget\n"
        )

        self.assertEqual(
            parse_numbered_suggestions(text),
            [
                "feat: add the widget",
                "fix: stop the widget crashing",
                "chore: tidy the widget",
            ],
        )

    def test_a_suggestion_keeps_its_body(self):
        """An item keeps the lines indented under it, so a message with a
        body stays whole instead of being cut down to its subject. The indent
        is what marked them as the item's — it is not part of the message."""
        text = "1. feat: add it\n\n   why it was added\n\n2. feat: add it, briefly\n"

        self.assertEqual(
            parse_numbered_suggestions(text),
            ["feat: add it\n\nwhy it was added", "feat: add it, briefly"],
        )

    def test_the_tools_closing_remarks_are_not_part_of_the_last_message(self):
        """A tool asked for a list has something to say about it afterwards.
        That prose follows the last item, but it isn't part of it — picking
        that row must not drop "My pick: …" into the commit message."""
        text = (
            "1. feat: add the widget\n"
            "2. fix: stop the widget crashing\n"
            "\n"
            "My pick: #2 — it names the actual bug.\n"
        )

        self.assertEqual(
            parse_numbered_suggestions(text),
            ["feat: add the widget", "fix: stop the widget crashing"],
        )

    def test_prose_between_the_items_ends_only_the_item_it_follows(self):
        """Ending the parse there would lose every suggestion below the
        comment, so only the open item is closed."""
        text = (
            "1. feat: add the widget\n"
            "This one leads with the feature.\n"
            "2. fix: stop the widget crashing\n"
        )

        self.assertEqual(
            parse_numbered_suggestions(text),
            ["feat: add the widget", "fix: stop the widget crashing"],
        )

    def test_a_body_written_without_indentation_reads_as_the_end_of_its_item(self):
        """The cost of the rule, and the reason the pick stays editable."""
        text = "1. feat: add it\nwhy it was added\n"

        self.assertEqual(parse_numbered_suggestions(text), ["feat: add it"])

    def test_indented_numbers_still_count(self):
        self.assertEqual(parse_numbered_suggestions("  1. feat: x\n"), ["feat: x"])

    def test_output_without_a_list_parses_as_nothing(self):
        """Which is what sends the whole output to the text area instead."""
        self.assertEqual(parse_numbered_suggestions("feat: just the one message\n"), [])

    def test_a_bare_number_is_not_a_suggestion(self):
        """`1.` with nothing after it introduces no message."""
        self.assertEqual(parse_numbered_suggestions("1.\n2. feat: x\n"), ["feat: x"])

    def test_markdown_delimiters_come_off_the_message(self):
        """A tool writing a list writes it as Markdown; the commit message is
        plain text, so the bold markers and code spans don't go into it."""
        text = "1. **feat: add the widget**\n2. `fix: stop `widget.py` crashing`\n"

        self.assertEqual(
            parse_numbered_suggestions(text),
            ["feat: add the widget", "fix: stop widget.py crashing"],
        )

    def test_a_delimiter_left_unclosed_comes_off_too(self):
        """An item ends at the first unindented line, which can cut it off
        mid-emphasis — the opening marker still must not survive."""
        self.assertEqual(parse_numbered_suggestions("1. **feat: add it\n"), ["feat: add it"])

    def test_a_fenced_message_loses_its_fences_and_not_its_body(self):
        """The fence lines go whole: stripping their backticks would leave a
        language tag behind as a line of the message."""
        text = "1. feat: add it\n   ```text\n   why it was added\n   ```\n"

        self.assertEqual(parse_numbered_suggestions(text), ["feat: add it\nwhy it was added"])

    def test_an_item_that_is_only_markup_is_not_a_suggestion(self):
        """Nothing is left of it once the markers come off."""
        self.assertEqual(parse_numbered_suggestions("1. ```\n2. feat: x\n"), ["feat: x"])


class TestSuggestionDialog(unittest.TestCase):
    """The picker: one row per suggestion, and the pick goes back to the
    commit dialog as editable text."""

    def _dialog(self) -> Any:
        return SuggestionDialog(["feat: add it\n\nthe body", "fix: repair it"])

    def test_rows_are_numbered_and_cut_to_the_subject(self):
        self.assertEqual(
            self._dialog().option_labels(),
            [f"1. feat: add it{TRUNCATION_MARKER}", "2. fix: repair it"],
        )

    def test_picking_a_row_dismisses_with_the_whole_message(self):
        """The list shows subjects, but what comes back is the body too."""
        dialog = self._dialog()
        with patch.object(SuggestionDialog, "dismiss") as dismiss:
            dialog.pick(0)

        dismiss.assert_called_once_with("feat: add it\n\nthe body")

    def test_a_digit_picks_that_row(self):
        dialog = self._dialog()
        event = _key_event("2", character="2")
        with patch.object(SuggestionDialog, "dismiss") as dismiss:
            dialog.on_key(event)

        dismiss.assert_called_once_with("fix: repair it")
        event.stop.assert_called_once_with()

    def test_a_digit_past_the_end_of_the_list_does_nothing(self):
        dialog = self._dialog()
        with patch.object(SuggestionDialog, "dismiss") as dismiss:
            dialog.on_key(_key_event("7", character="7"))

        dismiss.assert_not_called()

    def test_escape_dismisses_with_none(self):
        dialog = self._dialog()
        with patch.object(SuggestionDialog, "dismiss") as dismiss:
            dialog.on_key(_key_event("escape"))

        dismiss.assert_called_once_with(None)

    def test_arrow_keys_are_left_to_the_option_list(self):
        """Moving the cursor is the OptionList's job; claiming the key here
        would leave the list unnavigable."""
        dialog = self._dialog()
        event = _key_event("down")
        with patch.object(SuggestionDialog, "dismiss") as dismiss:
            dialog.on_key(event)

        dismiss.assert_not_called()
        event.stop.assert_not_called()

    def test_it_is_a_modal_screen_focused_on_the_list(self):
        self.assertTrue(issubclass(SuggestionDialog, ModalScreen))
        self.assertEqual(SuggestionDialog.AUTO_FOCUS, "#suggestion-list")


class TestCommitDraftOutputPane(unittest.TestCase):
    """The log under the buttons: what the drafting tool printed, while it is
    still printing it."""

    def _dialog(self) -> tuple[Any, dict[str, Any]]:
        widgets = {
            selector: MagicMock()
            for selector in (
                "#commit-output",
                "#commit-output-content",
                "#commit-status",
                "#commit-draft",
            )
        }
        patcher = patch.object(
            CommitDialog, "query_one", side_effect=lambda selector, *a, **k: widgets[selector]
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return CommitDialog(prefill=""), widgets

    def test_the_pane_stays_hidden_until_something_runs(self):
        dialog, widgets = self._dialog()

        dialog._render_output()

        self.assertFalse(widgets["#commit-output"].display)

    def test_each_line_is_appended_and_kept_in_view(self):
        dialog, widgets = self._dialog()
        dialog.set_drafting(True)

        dialog.append_output("cloning")
        dialog.append_output("thinking")

        widgets["#commit-output-content"].update.assert_called_with("cloning\nthinking")
        self.assertTrue(widgets["#commit-output"].display)
        # Pinned to the bottom, so the newest line is the visible one.
        widgets["#commit-output"].scroll_end.assert_called_with(animate=False)

    def test_only_the_newest_lines_are_kept(self):
        """A chatty tool would otherwise grow the log without bound."""
        dialog, _ = self._dialog()
        dialog.set_drafting(True)

        for index in range(COMMIT_DRAFT_OUTPUT_LINES + 10):
            dialog.append_output(f"line {index}")

        self.assertEqual(len(dialog.output_lines), COMMIT_DRAFT_OUTPUT_LINES)
        self.assertEqual(dialog.output_lines[-1], f"line {COMMIT_DRAFT_OUTPUT_LINES + 9}")

    def test_a_finished_run_leaves_its_output_on_screen(self):
        """What the tool said about a message it could not write is exactly
        what the user needs to read."""
        dialog, widgets = self._dialog()
        dialog.set_drafting(True)
        dialog.append_output("no API key")

        dialog.set_drafting(False)

        self.assertEqual(dialog.output_lines, ["no API key"])
        self.assertTrue(widgets["#commit-output"].display)

    def test_a_new_run_starts_from_an_empty_log(self):
        dialog, _ = self._dialog()
        dialog.set_drafting(True)
        dialog.append_output("first run")
        dialog.set_drafting(False)

        dialog.set_drafting(True)

        self.assertEqual(dialog.output_lines, [])


class TestCommitDialogCss(unittest.TestCase):
    def test_commit_dialog_is_a_modal_screen(self):
        """Modality comes from the screen stack now, not an overlay layer:
        that is what dims the background and contains focus in the text area."""
        self.assertTrue(issubclass(CommitDialog, ModalScreen))
        self.assertEqual(CommitDialog.AUTO_FOCUS, "#commit-message")

    def test_commit_dialog_centres_its_body(self):
        self.assertIn("align: center middle", CommitDialog.DEFAULT_CSS)
        self.assertIn("#commit-body", CommitDialog.DEFAULT_CSS)

    def test_commit_dialog_spans_the_screen(self):
        """A commit message is prose, so the box takes the full width rather
        than the 70 cells it used to be pinned to."""
        body = CommitDialog.DEFAULT_CSS.split("#commit-body")[1].split("}")[0]

        self.assertIn("width: 100%", body)
        self.assertNotIn("width: 70", body)


if __name__ == "__main__":
    unittest.main()


class TestRepoMenu(unittest.TestCase):
    """Pull / push / stash live in their own menu: they act on the repo, not
    on the file under the cursor, which is what the File menu is about."""

    def test_repo_menu_sits_between_file_and_view(self):
        self.assertEqual(
            [menu_id for _, menu_id in MENU_BAR][:3], ["menu_file", "menu_repo", "menu_view"]
        )

    def test_repo_menu_runs_the_four_repo_actions(self):
        self.assertEqual(
            [action for _, action in REPO_MENU],
            ["pull", "push", "stash", "stash_pop"],
        )

    def test_repo_menu_accelerators_are_distinct(self):
        keys = [_menu_mnemonic_key(label) for label, _ in REPO_MENU]
        self.assertEqual(keys, ["p", "u", "s", "o"])
        self.assertEqual(len(set(keys)), len(keys))

    def test_repo_menu_entries_carry_their_shortcut_hint(self):
        hints = {_menu_plain_label(label): _menu_hint(action) for label, action in REPO_MENU}
        self.assertEqual(hints["Pull"], "P")
        self.assertEqual(hints["Push"], "Shift+P")
        self.assertEqual(hints["Stash"], "Z")
        self.assertEqual(hints["Stash pop"], "Shift+Z")


class TestStashActions(unittest.TestCase):
    """`z` stashes, `Shift+Z` pops. Both ask first: one empties the worktree,
    the other refills it and can conflict."""

    def _app(self, entries, *, stash_entries=None):
        app = _mock_app()
        app.file_list_mode = MODE_SHORT
        app.status_entries = GitFilelist(entries)
        app.git.load_status.return_value = GitFilelist(entries)
        app.git.stash_command.side_effect = lambda filenames=None: (
            ["git", "stash", "push", "--include-untracked"]
            + (["--", *filenames] if filenames else [])
        )
        app.git.stash_pop_command.return_value = ["git", "stash", "pop"]
        app.git.stash_entries.return_value = list(stash_entries or [])
        app.git.stash.return_value = MagicMock(returncode=0, stdout="", stderr="")
        app.git.stash_pop.return_value = MagicMock(returncode=0, stdout="", stderr="")
        return app, _DialogProbe(app)

    def test_stash_with_no_selection_offers_the_whole_worktree(self):
        app, dialog = self._app([GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")])

        app.action_stash()

        dialog.assert_confirm(
            "Stash all changes?",
            ["git stash push --include-untracked"],
        )

    def test_stash_with_a_selection_limits_the_pathspec_to_it(self):
        a = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        b = GitEntry(GitCode.UNTRACKED_UNTRACKED, "pkg/b.py")
        c = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/c.py")
        app, dialog = self._app([a, b, c])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_stash()

        dialog.assert_confirm(
            "Stash 2 file(s)?",
            ["git stash push --include-untracked -- pkg/a.py pkg/b.py"],
        )

    def test_stash_on_a_clean_tree_notifies_instead_of_asking(self):
        app, dialog = self._app([])

        with patch.object(app, "notify") as notify:
            app.action_stash()

        notify.assert_called_once_with("Nothing to stash")
        dialog.assert_not_shown()

    def test_stash_leaves_submodule_files_out_and_says_how_many(self):
        """A pathspec can't name a path in another repository, so those
        entries drop out — visibly, in the dialog that asks."""
        inner = GitEntry(GitCode.UNMODIFIED_MODIFIED, "sub/inner.py", submodule="sub")
        outer = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        app, dialog = self._app([inner, outer])
        app.status_entries.toggle_selection(0)
        app.status_entries.toggle_selection(1)

        app.action_stash()

        self.assertEqual(dialog.prompt(), "Stash 1 file(s)?")
        self.assertEqual(
            dialog.commands(),
            [
                "git stash push --include-untracked -- pkg/a.py",
                "",
                "-- 1 file(s) inside a submodule are left alone --",
            ],
        )

    def test_stash_of_only_submodule_files_is_refused(self):
        inner = GitEntry(GitCode.UNMODIFIED_MODIFIED, "sub/inner.py", submodule="sub")
        app, dialog = self._app([inner])
        app.status_entries.toggle_selection(0)

        with patch.object(app, "notify") as notify:
            app.action_stash()

        notify.assert_called_once_with("Cannot stash files inside a submodule")
        dialog.assert_not_shown()

    def test_confirming_stash_runs_it_and_reloads_the_status(self):
        app, dialog = self._app([GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")])
        app.action_stash()

        with patch.object(app, "_load_status") as load, patch.object(app, "notify") as notify:
            dialog.confirm()

        app.git.stash.assert_called_once_with(filenames=None)
        notify.assert_called_once_with("Stashed changes")
        load.assert_called_once()

    def test_cancelling_stash_runs_nothing(self):
        app, dialog = self._app([GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")])
        app.action_stash()

        with patch.object(app, "_focus_active_view"):
            dialog.cancel()

        app.git.stash.assert_not_called()

    def test_stash_failure_reports_git_stderr(self):
        app, dialog = self._app([GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")])
        app.git.stash.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: pathspec did not match\n"
        )
        app.action_stash()

        with patch.object(app, "_load_status"), patch.object(app, "notify") as notify:
            dialog.confirm()

        notify.assert_called_once_with("git stash failed: error: pathspec did not match")

    def test_stash_pop_names_the_entry_it_would_reapply(self):
        """Which entry is on top is exactly what someone who stashed twice
        cannot remember, so the question says it."""
        app, dialog = self._app([], stash_entries=["stash@{0}: WIP on master: abc123 the newest"])

        app.action_stash_pop()

        dialog.assert_confirm(
            "Pop stash@{0}: WIP on master: abc123 the newest?",
            ["git stash pop"],
        )

    def test_stash_pop_says_how_many_entries_are_waiting(self):
        app, dialog = self._app(
            [],
            stash_entries=["stash@{0}: WIP on master: a newest", "stash@{1}: WIP on master: b"],
        )

        app.action_stash_pop()

        self.assertEqual(
            dialog.commands(),
            ["git stash pop", "", "-- 2 entries stashed; pop takes the newest --"],
        )

    def test_stash_pop_cuts_a_long_stash_subject_down(self):
        app, dialog = self._app([], stash_entries=["stash@{0}: WIP on master: " + "x" * 200])

        app.action_stash_pop()

        self.assertTrue(dialog.prompt().endswith(f"{TRUNCATION_MARKER}?"))
        self.assertLess(len(dialog.prompt()), 80)

    def test_stash_pop_with_an_empty_stash_notifies_instead_of_asking(self):
        app, dialog = self._app([])

        with patch.object(app, "notify") as notify:
            app.action_stash_pop()

        notify.assert_called_once_with("No stash entries to pop")
        dialog.assert_not_shown()

    def test_confirming_stash_pop_runs_it_and_reloads_the_status(self):
        app, dialog = self._app([], stash_entries=["stash@{0}: WIP on master: abc123 x"])
        app.action_stash_pop()

        with patch.object(app, "_load_status") as load, patch.object(app, "notify") as notify:
            dialog.confirm()

        app.git.stash_pop.assert_called_once_with()
        notify.assert_called_once_with("Popped the newest stash entry")
        load.assert_called_once()

    def test_a_conflicted_pop_reports_gits_own_message(self):
        app, dialog = self._app([], stash_entries=["stash@{0}: WIP on master: abc123 x"])
        app.git.stash_pop.return_value = MagicMock(
            returncode=1, stdout="", stderr="CONFLICT (content): Merge conflict in pkg/a.py\n"
        )
        app.action_stash_pop()

        with patch.object(app, "_load_status"), patch.object(app, "notify") as notify:
            dialog.confirm()

        notify.assert_called_once_with(
            "git stash pop failed: CONFLICT (content): Merge conflict in pkg/a.py"
        )


class TestRemoteActions(unittest.TestCase):
    """`p` pulls and `Shift+P` pushes. Both confirm first, then run on a
    thread worker so the network doesn't freeze the TUI."""

    def _app(self, *, upstream: str | None = "origin/master", remotes=("origin",), branch="master"):
        app = _mock_app()
        app.git.upstream_branch.return_value = upstream
        app.git.remote_names.return_value = list(remotes)
        app.git.branch_name.return_value = branch
        app.git.pull_command.return_value = ["git", "pull", "--ff-only"]
        app.git.push_command.return_value = (
            ["git", "push"]
            if upstream is not None
            else ["git", "push", "--set-upstream", remotes[0] if remotes else "origin", branch]
        )
        app.git.pull.return_value = MagicMock(
            returncode=0, stdout="Already up to date.\n", stderr=""
        )
        app.git.push.return_value = MagicMock(
            returncode=0, stdout="", stderr="Everything up-to-date\n"
        )
        return app, _DialogProbe(app)

    def test_pull_confirms_against_the_upstream_it_would_use(self):
        app, dialog = self._app()

        app.action_pull()

        dialog.assert_confirm("Pull from origin/master?", ["git pull --ff-only"])

    def test_pull_without_a_remote_is_refused_before_the_dialog(self):
        app, dialog = self._app(remotes=())

        with patch.object(app, "notify") as notify:
            app.action_pull()

        notify.assert_called_once_with("No remote is configured for this repository")
        dialog.assert_not_shown()

    def test_pull_without_an_upstream_points_at_push(self):
        """`--ff-only` has no ref to fast-forward to, and the fix is the push
        that sets one."""
        app, dialog = self._app(upstream=None, branch="feature")

        with patch.object(app, "notify") as notify:
            app.action_pull()

        notify.assert_called_once_with("feature has no upstream branch — push it first (Shift+P)")
        dialog.assert_not_shown()

    def test_push_confirms_against_the_upstream(self):
        app, dialog = self._app()

        app.action_push()

        dialog.assert_confirm("Push master to origin/master?", ["git push"])

    def test_push_says_when_it_would_publish_the_branch(self):
        """A branch with no upstream is created on the remote by this push —
        a bigger step than updating one, and the question is where to say so."""
        app, dialog = self._app(upstream=None, branch="feature")

        app.action_push()

        dialog.assert_confirm(
            "Push feature to origin and set it as upstream?",
            ["git push --set-upstream origin feature"],
        )

    def test_push_without_a_remote_is_refused_before_the_dialog(self):
        app, dialog = self._app(remotes=())

        with patch.object(app, "notify") as notify:
            app.action_push()

        notify.assert_called_once_with("No remote is configured for this repository")
        dialog.assert_not_shown()

    def test_pull_warns_about_a_submodule_on_another_branch(self):
        """The parent's history is about to move past a gitlink into a
        submodule nobody is on the branch of, and the confirmation is the last
        thing between the keypress and the network."""
        app, dialog = self._app()
        app._submodule_mismatches = [("libs/core", "dev", "master")]

        app.action_pull()

        dialog.assert_confirm(
            "Pull from origin/master?",
            [
                "git pull --ff-only",
                "",
                "-- Warning: submodule 'libs/core' is on branch 'dev' but parent is on 'master' --",
            ],
        )

    def test_push_warns_once_per_mismatched_submodule(self):
        app, dialog = self._app()
        app._submodule_mismatches = [
            ("libs/core", "dev", "master"),
            ("vendor/tool", None, "master"),
        ]

        app.action_push()

        dialog.assert_confirm(
            "Push master to origin/master?",
            [
                "git push",
                "",
                "-- Warning: submodule 'libs/core' is on branch 'dev' but parent is on 'master' --",
                (
                    "-- Warning: submodule 'vendor/tool' is on branch '(detached HEAD)' "
                    "but parent is on 'master' --"
                ),
            ],
        )

    def test_matching_submodule_branches_add_nothing_to_the_question(self):
        app, dialog = self._app()
        app._submodule_mismatches = []

        app.action_push()

        dialog.assert_confirm("Push master to origin/master?", ["git push"])

    def test_confirming_a_pull_runs_it_and_reloads_both_views(self):
        app, dialog = self._app()
        app.action_pull()

        with (
            patch.object(app, "_load_status") as status,
            patch.object(app, "_load_commits") as commits,
            patch.object(app, "notify") as notify,
        ):
            dialog.confirm()

        app.git.pull.assert_called_once_with()
        status.assert_called_once()
        commits.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in notify.call_args_list],
            ["Pull in progress…", "Pull: Already up to date."],
        )

    def test_confirming_a_push_reports_the_last_line_git_printed(self):
        app, dialog = self._app()
        app.action_push()

        with (
            patch.object(app, "_load_status"),
            patch.object(app, "_load_commits"),
            patch.object(app, "notify") as notify,
        ):
            dialog.confirm()

        app.git.push.assert_called_once_with()
        self.assertEqual(notify.call_args_list[-1].args[0], "Push: Everything up-to-date")

    def test_a_rejected_push_reports_the_reason_not_gits_hints(self):
        app, dialog = self._app()
        app.git.push.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr=(
                "! [rejected] master -> master (fetch first)\n"
                "hint: Updates were rejected because the remote contains work\n"
                "hint: you do not have locally.\n"
            ),
        )
        app.action_push()

        with (
            patch.object(app, "_load_status"),
            patch.object(app, "_load_commits"),
            patch.object(app, "notify") as notify,
        ):
            dialog.confirm()

        self.assertEqual(
            notify.call_args_list[-1].args[0],
            "Push failed: ! [rejected] master -> master (fetch first)",
        )

    def test_a_command_that_cannot_start_is_reported_like_a_failure(self):
        app, dialog = self._app()
        app.git.push.side_effect = OSError("git: command not found")
        app.action_push()

        with (
            patch.object(app, "_load_status"),
            patch.object(app, "_load_commits"),
            patch.object(app, "notify") as notify,
        ):
            dialog.confirm()

        self.assertEqual(
            notify.call_args_list[-1].args[0],
            "Push failed: git: command not found",
        )

    def test_a_second_push_while_one_is_running_is_refused(self):
        """`exclusive=True` cancels a superseded worker's task but not its
        thread, so the guard is what stops a second push reaching the wire."""
        app, dialog = self._app()
        app._remote_running = True

        with patch.object(app, "notify") as notify:
            app.action_push()
            app.action_pull()

        self.assertEqual(
            [call.args[0] for call in notify.call_args_list],
            ["A pull or push is already running"] * 2,
        )
        dialog.assert_not_shown()

    def test_the_guard_is_released_when_the_command_comes_back(self):
        app, dialog = self._app()
        app.action_pull()

        with (
            patch.object(app, "_load_status"),
            patch.object(app, "_load_commits"),
            patch.object(app, "notify"),
        ):
            dialog.confirm()

        self.assertFalse(app._remote_running)

    def test_cancelling_runs_nothing(self):
        app, dialog = self._app()
        app.action_push()

        with patch.object(app, "_focus_active_view"):
            dialog.cancel()

        app.git.push.assert_not_called()
        self.assertFalse(app._remote_running)


class TestQuit(unittest.TestCase):
    """F10 ends the git reads rather than waiting for them.

    A thread worker can only be waited for — Textual joins them on the way
    out — so a quit pressed during the startup `git status` / `git log` used
    to sit there until git returned, which reads as a dropped keypress.
    """

    def test_quit_shuts_git_down_before_exiting(self):
        app = _mock_app()
        app.exit = MagicMock()

        app.action_quit()

        app.git.shutdown.assert_called_once_with()
        app.exit.assert_called_once_with()

    def test_quit_leaves_a_running_pull_or_push_alone(self):
        """That one is a write, and half of it is already on the wire: the
        user asked to close the app, not to cancel the command."""
        app = _mock_app()
        app.exit = MagicMock()
        app._remote_running = True

        app.action_quit()

        app.git.shutdown.assert_not_called()
        app.exit.assert_called_once_with()
