"""Git data types and command wrappers used by the application."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import overload

# Colour git writes when the user's config forces it on. `-c color.ui=false`
# (see `_run_in`) turns the default off, but per-command settings such as
# `color.diff = always` still win over it, so whatever escapes come through
# are stripped here: the UI renders the strings it gets literally, and raw
# SGR sequences would show up as garbage in the diff and commit panes.
ANSI_SGR_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Commit:
    hash: str
    author: str
    date: str
    subject: str


class GitStatus(str, Enum):
    UNMODIFIED = " "
    MODIFIED = "M"
    TYPE_CHANGED = "T"
    ADDED = "A"
    DELETED = "D"
    RENAMED = "R"
    COPIED = "C"
    UPDATED_UNMERGED = "U"
    UNTRACKED = "?"
    IGNORED = "!"


LONG_STATUS_DESCRIPTIONS: dict[GitStatus, str] = {
    GitStatus.MODIFIED: "modified",
    GitStatus.TYPE_CHANGED: "typechange",
    GitStatus.ADDED: "new file",
    GitStatus.DELETED: "deleted",
    GitStatus.RENAMED: "renamed",
    GitStatus.COPIED: "copied",
    GitStatus.UPDATED_UNMERGED: "unmerged",
    GitStatus.UNTRACKED: "untracked",
    GitStatus.IGNORED: "ignored",
}


class GitCode(str, Enum):
    """Two-character porcelain status codes (staged + unstaged).

    Members enumerate every ``GitStatus`` × ``GitStatus`` combination, named
    ``<staged>_<unstaged>`` with the raw two-character value.
    """

    UNMODIFIED_UNMODIFIED = "  "
    UNMODIFIED_MODIFIED = " M"
    UNMODIFIED_TYPE_CHANGED = " T"
    UNMODIFIED_ADDED = " A"
    UNMODIFIED_DELETED = " D"
    UNMODIFIED_RENAMED = " R"
    UNMODIFIED_COPIED = " C"
    UNMODIFIED_UPDATED_UNMERGED = " U"
    UNMODIFIED_UNTRACKED = " ?"
    UNMODIFIED_IGNORED = " !"
    MODIFIED_UNMODIFIED = "M "
    MODIFIED_MODIFIED = "MM"
    MODIFIED_TYPE_CHANGED = "MT"
    MODIFIED_ADDED = "MA"
    MODIFIED_DELETED = "MD"
    MODIFIED_RENAMED = "MR"
    MODIFIED_COPIED = "MC"
    MODIFIED_UPDATED_UNMERGED = "MU"
    MODIFIED_UNTRACKED = "M?"
    MODIFIED_IGNORED = "M!"
    TYPE_CHANGED_UNMODIFIED = "T "
    TYPE_CHANGED_MODIFIED = "TM"
    TYPE_CHANGED_TYPE_CHANGED = "TT"
    TYPE_CHANGED_ADDED = "TA"
    TYPE_CHANGED_DELETED = "TD"
    TYPE_CHANGED_RENAMED = "TR"
    TYPE_CHANGED_COPIED = "TC"
    TYPE_CHANGED_UPDATED_UNMERGED = "TU"
    TYPE_CHANGED_UNTRACKED = "T?"
    TYPE_CHANGED_IGNORED = "T!"
    ADDED_UNMODIFIED = "A "
    ADDED_MODIFIED = "AM"
    ADDED_TYPE_CHANGED = "AT"
    ADDED_ADDED = "AA"
    ADDED_DELETED = "AD"
    ADDED_RENAMED = "AR"
    ADDED_COPIED = "AC"
    ADDED_UPDATED_UNMERGED = "AU"
    ADDED_UNTRACKED = "A?"
    ADDED_IGNORED = "A!"
    DELETED_UNMODIFIED = "D "
    DELETED_MODIFIED = "DM"
    DELETED_TYPE_CHANGED = "DT"
    DELETED_ADDED = "DA"
    DELETED_DELETED = "DD"
    DELETED_RENAMED = "DR"
    DELETED_COPIED = "DC"
    DELETED_UPDATED_UNMERGED = "DU"
    DELETED_UNTRACKED = "D?"
    DELETED_IGNORED = "D!"
    RENAMED_UNMODIFIED = "R "
    RENAMED_MODIFIED = "RM"
    RENAMED_TYPE_CHANGED = "RT"
    RENAMED_ADDED = "RA"
    RENAMED_DELETED = "RD"
    RENAMED_RENAMED = "RR"
    RENAMED_COPIED = "RC"
    RENAMED_UPDATED_UNMERGED = "RU"
    RENAMED_UNTRACKED = "R?"
    RENAMED_IGNORED = "R!"
    COPIED_UNMODIFIED = "C "
    COPIED_MODIFIED = "CM"
    COPIED_TYPE_CHANGED = "CT"
    COPIED_ADDED = "CA"
    COPIED_DELETED = "CD"
    COPIED_RENAMED = "CR"
    COPIED_COPIED = "CC"
    COPIED_UPDATED_UNMERGED = "CU"
    COPIED_UNTRACKED = "C?"
    COPIED_IGNORED = "C!"
    UPDATED_UNMERGED_UNMODIFIED = "U "
    UPDATED_UNMERGED_MODIFIED = "UM"
    UPDATED_UNMERGED_TYPE_CHANGED = "UT"
    UPDATED_UNMERGED_ADDED = "UA"
    UPDATED_UNMERGED_DELETED = "UD"
    UPDATED_UNMERGED_RENAMED = "UR"
    UPDATED_UNMERGED_COPIED = "UC"
    UPDATED_UNMERGED_UPDATED_UNMERGED = "UU"
    UPDATED_UNMERGED_UNTRACKED = "U?"
    UPDATED_UNMERGED_IGNORED = "U!"
    UNTRACKED_UNMODIFIED = "? "
    UNTRACKED_MODIFIED = "?M"
    UNTRACKED_TYPE_CHANGED = "?T"
    UNTRACKED_ADDED = "?A"
    UNTRACKED_DELETED = "?D"
    UNTRACKED_RENAMED = "?R"
    UNTRACKED_COPIED = "?C"
    UNTRACKED_UPDATED_UNMERGED = "?U"
    UNTRACKED_UNTRACKED = "??"
    UNTRACKED_IGNORED = "?!"
    IGNORED_UNMODIFIED = "! "
    IGNORED_MODIFIED = "!M"
    IGNORED_TYPE_CHANGED = "!T"
    IGNORED_ADDED = "!A"
    IGNORED_DELETED = "!D"
    IGNORED_RENAMED = "!R"
    IGNORED_COPIED = "!C"
    IGNORED_UPDATED_UNMERGED = "!U"
    IGNORED_UNTRACKED = "!?"
    IGNORED_IGNORED = "!!"

    @property
    def staged(self) -> GitStatus:
        return GitStatus(self.value[0])

    @property
    def unstaged(self) -> GitStatus:
        return GitStatus(self.value[1])

    @property
    def is_untracked(self) -> bool:
        return self.value == "??"

    def contains(self, status: GitStatus) -> bool:
        return self.staged is status or self.unstaged is status

    @property
    def long_description(self) -> str:
        """Human-readable status mirroring `git status` long-format labels."""
        if self.is_untracked:
            return "untracked"
        if self.value == "!!":
            return "ignored"
        parts: list[str] = []
        if self.staged != GitStatus.UNMODIFIED:
            parts.append(f"{LONG_STATUS_DESCRIPTIONS[self.staged]} (staged)")
        if self.unstaged != GitStatus.UNMODIFIED:
            parts.append(f"{LONG_STATUS_DESCRIPTIONS[self.unstaged]} (not staged)")
        return ", ".join(parts) or "unmodified"

    @property
    def has_staged_changes(self) -> bool:
        """True when `git restore --staged <file>` would do something."""
        return self.staged != GitStatus.UNMODIFIED and not self.is_untracked

    @property
    def has_unstaged_changes(self) -> bool:
        """True when `git add <file>` would do something (includes untracked)."""
        return self.unstaged != GitStatus.UNMODIFIED

    @property
    def is_restorable(self) -> bool:
        """True when the file can be reset to the state it had at HEAD.

        Ignored and unmerged entries are skipped: ignored files aren't a
        user concern, and unmerged (conflict) states need manual resolution
        rather than a blanket restore.
        """
        if self.value == "!!":
            return False
        if self.contains(GitStatus.UPDATED_UNMERGED):
            return False
        if self.is_untracked:
            return True
        return self.staged != GitStatus.UNMODIFIED or self.unstaged != GitStatus.UNMODIFIED

    @property
    def is_deletable(self) -> bool:
        """True when DELETE has a well-defined operation for the file.

        Skips ignored, unmerged, and entries whose worktree copy is already
        gone with no further index work to do (`D ` and `DD`). The remaining
        ` D` (unstaged delete) is deletable so the user can stage that
        removal via DELETE.
        """
        if self.value == "!!":
            return False
        if self.contains(GitStatus.UPDATED_UNMERGED):
            return False
        worktree_copy_already_gone = self.staged == GitStatus.DELETED and self.unstaged in (
            GitStatus.UNMODIFIED,
            GitStatus.DELETED,
        )
        return not worktree_copy_already_gone


@dataclass
class GitEntry:
    code: GitCode
    filename: str
    submodule: str | None = None


DEFAULT_MTIME_FORMAT = "%Y-%m-%d %H:%M"
DEFAULT_STATUS_WIDTH = len("Status")
DIRECTORY_SIZE_LABEL = "<DIR>"


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "K", "M", "G"):
        if value < 1024 or unit == "G":
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


def _entry_stat(repo_path: str, filename: str, mtime_format: str) -> tuple[str, str]:
    candidate = filename.split(" -> ")[-1]
    try:
        st = os.stat(os.path.join(repo_path, candidate))
    except OSError:
        return "-", "-"
    # A collapsed untracked directory: its inode size says nothing about what
    # is inside it, so show a marker the way a file manager does.
    size = DIRECTORY_SIZE_LABEL if stat.S_ISDIR(st.st_mode) else _format_size(st.st_size)
    # Read as UTC then convert back to the local zone, so the displayed wall
    # clock matches the user's timezone without relying on a naive datetime.
    local_mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).astimezone()
    return size, local_mtime.strftime(mtime_format)


STATUS_COLORS: dict[GitStatus, str] = {
    GitStatus.UNMODIFIED: "",
    GitStatus.MODIFIED: "bold yellow",
    GitStatus.TYPE_CHANGED: "bold #ff8800",
    GitStatus.ADDED: "bold green",
    GitStatus.DELETED: "bold red",
    GitStatus.RENAMED: "bold cyan",
    GitStatus.COPIED: "bold blue",
    GitStatus.UPDATED_UNMERGED: "bold #ff5555",
    GitStatus.UNTRACKED: "bold white",
    GitStatus.IGNORED: "#888888",
}

SUBMODULE_COLOR = "bold magenta"


def _styled(text: str, color: str) -> str:
    if not color:
        return text
    return f"[{color}]{text}[/{color}]"


def _render_status_code(
    entry: GitEntry,
    status_width: int,
    status_colors: Mapping[GitStatus, str],
    submodule_color: str,
) -> str:
    value = entry.code.value
    padding = " " * max(0, status_width - 2)
    if entry.submodule is not None:
        return _styled(value, submodule_color) + padding
    staged = _styled(value[0], status_colors[entry.code.staged])
    unstaged = _styled(value[1], status_colors[entry.code.unstaged])
    return f"{staged}{unstaged}{padding}"


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text.ljust(width)
    return text[: max(0, width - 1)] + "…"


def _entry_sort_key(entry: GitEntry) -> tuple[str, str]:
    return (entry.filename.casefold(), entry.filename)


@dataclass
class GitFilelist(Sequence[GitEntry]):
    """View model backing the short and long file-list views."""

    entries: list[GitEntry] = field(default_factory=list)
    highlighted_entry: GitEntry | None = None
    selected_filenames: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.entries = sorted(self.entries, key=_entry_sort_key)
        if self.highlighted_entry is not None:
            index = self.index_of(self.highlighted_entry)
            self.highlighted_entry = self.entry_at(index)
        self.selected_filenames = set(self.selected_filenames) & self._filenames()

    def _filenames(self) -> set[str]:
        return {entry.filename for entry in self.entries}

    @overload
    def __getitem__(self, index: int) -> GitEntry: ...
    @overload
    def __getitem__(self, index: slice) -> list[GitEntry]: ...
    def __getitem__(self, index: int | slice) -> GitEntry | list[GitEntry]:
        return self.entries[index]

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[GitEntry]:
        return iter(self.entries)

    def entry_at(self, index: int | None) -> GitEntry | None:
        if not isinstance(index, int) or not 0 <= index < len(self.entries):
            return None
        return self.entries[index]

    def index_of(self, entry: GitEntry) -> int | None:
        for index, candidate in enumerate(self.entries):
            if candidate.code == entry.code and candidate.filename == entry.filename:
                return index
        for index, candidate in enumerate(self.entries):
            if candidate.filename == entry.filename:
                return index
        # A file the list now shows folded into its untracked directory's
        # `dir/` row: that row is where the file went.
        for index, candidate in enumerate(self.entries):
            if candidate.filename.endswith("/") and entry.filename.startswith(candidate.filename):
                return index
        return None

    def set_highlighted_index(self, index: int | None) -> GitEntry | None:
        self.highlighted_entry = self.entry_at(index)
        return self.highlighted_entry

    def is_selected(self, index: int | None) -> bool:
        entry = self.entry_at(index)
        return entry is not None and entry.filename in self.selected_filenames

    def toggle_selection(self, index: int | None) -> GitEntry | None:
        entry = self.entry_at(index)
        if entry is None:
            return None
        if entry.filename in self.selected_filenames:
            self.selected_filenames.discard(entry.filename)
        else:
            self.selected_filenames.add(entry.filename)
        return entry

    def clear_selections(self) -> None:
        self.selected_filenames.clear()

    def restore_selections(self, filenames: set[str]) -> None:
        self.selected_filenames = set(filenames) & self._filenames()

    def selected_entries(self) -> list[GitEntry]:
        return [e for e in self.entries if e.filename in self.selected_filenames]

    def status_message(self) -> str:
        if self.entries:
            return f"{len(self.entries)} file(s) changed"
        return "Nothing to commit, working tree clean"

    def row_text(
        self,
        entry: GitEntry,
        repo_path: str,
        *,
        status_width: int = DEFAULT_STATUS_WIDTH,
        name_width: int,
        size_width: int,
        mtime_width: int,
        mtime_format: str = DEFAULT_MTIME_FORMAT,
        status_colors: Mapping[GitStatus, str] = STATUS_COLORS,
        submodule_color: str = SUBMODULE_COLOR,
    ) -> str:
        code = _render_status_code(entry, status_width, status_colors, submodule_color)
        name = f"{_truncate(entry.filename, name_width):<{name_width}}"
        size, mtime = _entry_stat(repo_path, entry.filename, mtime_format)
        return f"{code}  {name}  {size:>{size_width}}  {mtime:>{mtime_width}}"

    def row_texts(
        self,
        repo_path: str,
        *,
        status_width: int = DEFAULT_STATUS_WIDTH,
        name_width: int,
        size_width: int,
        mtime_width: int,
        mtime_format: str = DEFAULT_MTIME_FORMAT,
        status_colors: Mapping[GitStatus, str] = STATUS_COLORS,
        submodule_color: str = SUBMODULE_COLOR,
    ) -> list[str]:
        return [
            self.row_text(
                entry,
                repo_path,
                status_width=status_width,
                name_width=name_width,
                size_width=size_width,
                mtime_width=mtime_width,
                mtime_format=mtime_format,
                status_colors=status_colors,
                submodule_color=submodule_color,
            )
            for entry in self.entries
        ]


def _untracked_directory_listing(path: str, display_name: str) -> str:
    """The files under a collapsed untracked directory, one relative path a line.

    Stands in for file content when the file list shows a whole untracked
    directory as one entry, so opening it still shows what staging or
    cleaning it would take along.
    """
    files: list[str] = []
    for root, dirs, names in os.walk(path):
        # An untracked nested repository collapses to `dir/` as well; its
        # object store is not what anyone opening the entry wants to read.
        dirs[:] = sorted(d for d in dirs if d != ".git")
        files.extend(os.path.relpath(os.path.join(root, n), path) for n in sorted(names))
    header = f"Untracked directory: {display_name} ({len(files)} file(s))"
    return "\n".join([header, "", *files])


class GIT:
    """Encapsulate all git commands used by the application."""

    def __init__(self, path: str = ".") -> None:
        self.path = path
        # Every git process that is running right now, so `shutdown()` can end
        # the ones a quit would otherwise have to wait out. The reads run on
        # worker threads, so both the set and its lock are touched from more
        # than one thread.
        self._running: set[subprocess.Popen[str]] = set()
        self._running_lock = threading.Lock()
        self._closed = False

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self._run_in(self.path, *args)

    def _run_in(self, cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
        argv = ["git", "-c", "color.ui=false", "-C", cwd, *args]
        # Spawning under the lock is what closes the window between the two
        # halves of `shutdown()`: started outside it, a process could be born
        # after the flag went up and before the set was read, and so run on
        # unwatched while the app was already on its way out.
        with self._running_lock:
            if self._closed:
                return subprocess.CompletedProcess(args=argv, returncode=1, stdout="", stderr="")
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._running.add(process)
        try:
            stdout, stderr = process.communicate()
        finally:
            with self._running_lock:
                self._running.discard(process)
        return subprocess.CompletedProcess(
            args=argv,
            returncode=process.returncode,
            stdout=ANSI_SGR_PATTERN.sub("", stdout or ""),
            stderr=stderr,
        )

    def shutdown(self) -> int:
        """Kill every git process still running, and run no more. One-way.

        `Popen` plus this method is what `subprocess.run()` used to be here.
        The cost of `run()` was that a call in flight could only be waited
        out: a read on a thread worker holds the process until git returns,
        and Textual joins its worker threads on shutdown, so a quit pressed
        during the startup `git status` sat there until it finished.

        Refusing the *next* call is half of it, and not the optional half: a
        read is several git commands one after another (`load_status` walks
        the submodules), so killing the one that happens to be running just
        hands the worker on to the next one. Every call after this returns
        the failure shape — `returncode` 1 and no output — which the readers
        already have to handle, because a git command can always fail.

        Returns how many processes were signalled.
        """
        with self._running_lock:
            self._closed = True
            processes = list(self._running)
        terminated = 0
        for process in processes:
            try:
                process.terminate()
            except (OSError, ValueError):  # already gone, or already reaped
                continue
            terminated += 1
        return terminated

    def _submodule_paths(self, abs_root: str) -> list[str]:
        """Submodule paths declared in <abs_root>/.gitmodules (relative to abs_root)."""
        gitmodules = os.path.join(abs_root, ".gitmodules")
        if not os.path.exists(gitmodules):
            return []
        result = self._run_in(
            abs_root,
            "config",
            "--file",
            ".gitmodules",
            "--get-regexp",
            r"^submodule\..*\.path$",
        )
        paths: list[str] = []
        for line in (result.stdout or "").splitlines():
            _, _, value = line.partition(" ")
            value = value.strip()
            if value:
                paths.append(value)
        return paths

    def _is_initialized_submodule(self, abs_path: str) -> bool:
        return os.path.exists(os.path.join(abs_path, ".git"))

    def _entry_target(self, entry: GitEntry) -> tuple[str, str]:
        """(cwd, inner_filename) for routing per-file commands at the right repo."""
        if entry.submodule:
            cwd = os.path.join(self.path, entry.submodule)
            return cwd, os.path.relpath(entry.filename, entry.submodule)
        return self.path, entry.filename

    def entry_command_filename(self, entry: GitEntry) -> str:
        """The filename as it appears in argv for this entry (inner for submodule)."""
        return self._entry_target(entry)[1]

    def load_commits(self) -> list[Commit]:
        """Run git log and parse the output into Commit objects."""
        result = self._run(
            "log",
            "--pretty=format:%H\x1f%an\x1f%ad\x1f%s",
            "--date=short",
            "-n",
            "200",
        )
        commits = []
        for line in result.stdout.splitlines():
            parts = line.split("\x1f", 3)
            if len(parts) == 4:
                commits.append(Commit(*parts))
        return commits

    def load_file_diff(self, entry: GitEntry) -> str:
        """Return the diff text for a status entry (staged + unstaged combined)."""
        cwd, name = self._entry_target(entry)
        staged, unstaged = entry.code.staged, entry.code.unstaged
        parts = []
        if staged not in (GitStatus.UNMODIFIED, GitStatus.UNTRACKED):
            result = self._run_in(cwd, "diff", "--cached", "--", name)
            if result.stdout:
                parts.append(result.stdout)
        if unstaged not in (GitStatus.UNMODIFIED, GitStatus.UNTRACKED):
            result = self._run_in(cwd, "diff", "--", name)
            if result.stdout:
                parts.append(result.stdout)
        if not parts:
            if entry.code.is_untracked:
                return f"Untracked file: {entry.filename}"
            return f"No diff available for {entry.filename}"
        return "\n".join(parts)

    def load_file_content(self, entry: GitEntry) -> str:
        """Return the raw text of an untracked entry's file on disk.

        Returns an informative message instead of raising if the file is
        unreadable (missing, permission denied) or binary.
        """
        cwd, name = self._entry_target(entry)
        path = os.path.join(cwd, name)
        if os.path.isdir(path):
            return _untracked_directory_listing(path, entry.filename)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            reason = exc.strerror or str(exc)
            return f"Cannot read file: {entry.filename} ({reason})"
        if b"\x00" in data:
            return f"Binary file: {entry.filename}"
        return data.decode("utf-8", errors="replace")

    def load_status(self, *, collapse_untracked_dirs: bool = False) -> GitFilelist:
        """Run git status --short and parse the output into a GitFilelist.

        `--untracked-files=all` expands untracked directories to the
        individual files inside them; gitignored files are excluded by
        default, so the listing already respects `.gitignore`.

        *collapse_untracked_dirs* switches that to `--untracked-files=normal`,
        which lists a directory holding nothing git has ever tracked as one
        `dir/` entry instead of every file below it. Git makes the call, so a
        directory with a tracked file anywhere inside still lists its
        untracked files one by one.

        Initialized submodules are recursively expanded: their parent rows
        are replaced with rows for the inner files (filenames prefixed with
        the submodule path; ``submodule`` set on each inner entry).
        """
        untracked_files = "normal" if collapse_untracked_dirs else "all"
        return GitFilelist(self._load_status_at("", untracked_files=untracked_files))

    def _load_status_at(self, rel_root: str, *, untracked_files: str) -> list[GitEntry]:
        abs_root = os.path.join(self.path, rel_root) if rel_root else self.path
        result = self._run_in(abs_root, "status", "--short", f"--untracked-files={untracked_files}")
        submodules = set(self._submodule_paths(abs_root))
        entries: list[GitEntry] = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            name = line[3:]
            # Submodule lines: recurse before parsing the code, since git
            # emits lowercase letters (e.g. " m") for submodule content
            # changes that aren't valid GitCode values. If the inner
            # working tree is clean (pointer-only change), we keep the
            # parent's row so the gitlink bump can still be staged and
            # committed; lowercase markers fall back to ` M`.
            if name in submodules:
                sub_abs = os.path.join(abs_root, name)
                if self._is_initialized_submodule(sub_abs):
                    sub_rel = os.path.join(rel_root, name) if rel_root else name
                    inner = self._load_status_at(sub_rel, untracked_files=untracked_files)
                    if inner:
                        entries.extend(inner)
                        continue
                    raw = line[:2]
                    try:
                        code = GitCode(raw)
                    except ValueError:
                        normalised = raw.upper().replace("?", " ")
                        try:
                            code = GitCode(normalised)
                        except ValueError:
                            code = GitCode(" M")
                    prefixed = os.path.join(rel_root, name) if rel_root else name
                    entries.append(GitEntry(code, prefixed, submodule=(rel_root or None)))
                    continue
            try:
                code = GitCode(line[:2])
            except ValueError:
                continue
            prefixed = os.path.join(rel_root, name) if rel_root else name
            entries.append(GitEntry(code, prefixed, submodule=(rel_root or None)))
        return entries

    def show_commit(self, commit_hash: str) -> str:
        """Return git show --stat output for a commit."""
        return self._run("show", "--stat", commit_hash).stdout

    def branch_name(self) -> str | None:
        """Return the current branch name, or None when detached / unknown."""
        result = self._run("branch", "--show-current")
        name = (result.stdout or "").strip()
        return name or None

    def repository_chain(self) -> list[str]:
        """Return the working trees from this repository out to the top-level one.

        The first entry is this repository's own top level, and each one after
        it is the superproject the previous one is a submodule of, so the last
        is the repository nothing contains. A repository that isn't a submodule
        yields a single entry; a path outside any repository yields none.
        """
        result = self._run("rev-parse", "--show-toplevel")
        toplevel = (result.stdout or "").strip()
        if result.returncode != 0 or not toplevel:
            return []
        chain = [toplevel]
        while True:
            result = self._run_in(chain[-1], "rev-parse", "--show-superproject-working-tree")
            parent = (result.stdout or "").strip()
            # The membership check stops a misconfigured gitlink that points
            # back into the chain from walking in circles.
            if result.returncode != 0 or not parent or parent in chain:
                return chain
            chain.append(parent)

    def _branch_name_in(self, cwd: str) -> str | None:
        result = self._run_in(cwd, "branch", "--show-current")
        name = (result.stdout or "").strip()
        return name or None

    def submodule_branch_mismatches(self) -> list[tuple[str, str | None, str | None]]:
        """Return mismatches between submodule branches and the parent's branch.

        Each tuple is ``(submodule_path, submodule_branch, parent_branch)`` for
        every initialized submodule (recursively) whose current branch differs
        from the root repo's current branch. ``None`` represents a detached
        HEAD on either side. Uninitialized submodules are skipped.
        """
        parent_branch = self.branch_name()
        mismatches: list[tuple[str, str | None, str | None]] = []
        self._collect_submodule_mismatches(self.path, "", parent_branch, mismatches)
        return mismatches

    def _collect_submodule_mismatches(
        self,
        abs_root: str,
        rel_root: str,
        parent_branch: str | None,
        mismatches: list[tuple[str, str | None, str | None]],
    ) -> None:
        for sub_path in self._submodule_paths(abs_root):
            sub_abs = os.path.join(abs_root, sub_path)
            if not self._is_initialized_submodule(sub_abs):
                continue
            sub_branch = self._branch_name_in(sub_abs)
            rel_path = os.path.join(rel_root, sub_path) if rel_root else sub_path
            if sub_branch != parent_branch:
                mismatches.append((rel_path, sub_branch, parent_branch))
            self._collect_submodule_mismatches(sub_abs, rel_path, parent_branch, mismatches)

    def staged_filenames(self) -> set[str]:
        """Filenames with staged changes (`git diff --cached --name-only`)."""
        result = self._run("diff", "--cached", "--name-only")
        return {line for line in (result.stdout or "").splitlines() if line}

    def commit_command(self, message: str) -> list[str]:
        """Return the argv that `commit` will run (for display/confirmation)."""
        return ["git", "commit", "-m", message]

    def commit(self, message: str) -> subprocess.CompletedProcess[str]:
        """Run `git commit -m <message>`."""
        return self._run("commit", "-m", message)

    def stage_command(self, filename: str) -> list[str]:
        """Return the argv that `stage_file` will run (for display/confirmation)."""
        return ["git", "add", "--", filename]

    def unstage_command(self, filename: str) -> list[str]:
        """Return the argv that `unstage_file` will run (for display/confirmation)."""
        return ["git", "restore", "--staged", "--", filename]

    def stage_file(self, filename: str) -> subprocess.CompletedProcess[str]:
        """Stage a single file in the parent repo (`git add -- <filename>`).

        Used for parent-only paths (e.g. re-staging externals after a
        commit). For an entry that may live inside a submodule, use
        :meth:`stage_entry` instead.
        """
        return self._run("add", "--", filename)

    def unstage_file(self, filename: str) -> subprocess.CompletedProcess[str]:
        """Unstage a single file in the parent repo."""
        return self._run("restore", "--staged", "--", filename)

    def stage_entry(self, entry: GitEntry) -> subprocess.CompletedProcess[str]:
        """`git add` an entry, routing into its submodule when applicable."""
        cwd, name = self._entry_target(entry)
        return self._run_in(cwd, "add", "--", name)

    def unstage_entry(self, entry: GitEntry) -> subprocess.CompletedProcess[str]:
        """`git restore --staged` an entry, routing into its submodule."""
        cwd, name = self._entry_target(entry)
        return self._run_in(cwd, "restore", "--staged", "--", name)

    def stage_command_for(self, entry: GitEntry) -> list[str]:
        """Argv preview for :meth:`stage_entry` (includes `-C` for submodules)."""
        cwd, name = self._entry_target(entry)
        if entry.submodule:
            return ["git", "-C", cwd, "add", "--", name]
        return self.stage_command(name)

    def unstage_command_for(self, entry: GitEntry) -> list[str]:
        """Argv preview for :meth:`unstage_entry`."""
        cwd, name = self._entry_target(entry)
        if entry.submodule:
            return ["git", "-C", cwd, "restore", "--staged", "--", name]
        return self.unstage_command(name)

    def commit_with_selection_commands(
        self, entries: list[GitEntry], message: str
    ) -> list[list[str]]:
        """Argv list for :meth:`commit_with_selection` (for the confirm dialog)."""
        groups: dict[str | None, list[GitEntry]] = {}
        for e in entries:
            groups.setdefault(e.submodule, []).append(e)
        sub_keys = sorted(
            (k for k in groups if k is not None),
            key=lambda p: p.count(os.sep),
            reverse=True,
        )
        commands: list[list[str]] = []
        for sub in sub_keys:
            sub_abs = os.path.join(self.path, sub)
            for e in groups[sub]:
                _, name = self._entry_target(e)
                commands.append(["git", "-C", sub_abs, "add", "--", name])
            commands.append(["git", "-C", sub_abs, "commit", "-m", message])
            enclosing = os.path.dirname(sub)
            enclosing_abs = os.path.join(self.path, enclosing) if enclosing else self.path
            gitlink = os.path.basename(sub) if enclosing else sub
            prefix = ["git"] if enclosing_abs == self.path else ["git", "-C", enclosing_abs]
            commands.append(prefix + ["add", "--", gitlink])
        if groups.get(None) or sub_keys:
            commands.append(["git", "commit", "-m", message])
        return commands

    def commit_with_selection(
        self, entries: list[GitEntry], message: str
    ) -> subprocess.CompletedProcess[str]:
        """Commit a multi-file selection that may cross submodule boundaries.

        Submodule files are committed inside their submodule first (deepest
        first, so nested submodules land before their parents), the
        resulting gitlink is staged in the enclosing repo, and a final
        parent commit picks up parent files plus all freshly-staged
        gitlinks.
        """
        groups: dict[str | None, list[GitEntry]] = {}
        for e in entries:
            groups.setdefault(e.submodule, []).append(e)
        sub_keys = sorted(
            (k for k in groups if k is not None),
            key=lambda p: p.count(os.sep),
            reverse=True,
        )
        last: subprocess.CompletedProcess[str] | None = None
        for sub in sub_keys:
            sub_abs = os.path.join(self.path, sub)
            for e in groups[sub]:
                _, name = self._entry_target(e)
                self._run_in(sub_abs, "add", "--", name)
            last = self._run_in(sub_abs, "commit", "-m", message)
            if last.returncode != 0:
                return last
            enclosing = os.path.dirname(sub)
            enclosing_abs = os.path.join(self.path, enclosing) if enclosing else self.path
            gitlink = os.path.basename(sub) if enclosing else sub
            self._run_in(enclosing_abs, "add", "--", gitlink)
        if groups.get(None) or sub_keys:
            last = self._run_in(self.path, "commit", "-m", message)
        if last is None:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        return last

    def restore_commands(self, entry: GitEntry) -> list[list[str]]:
        """Return the argv(s) that would reset *entry* to its HEAD state.

        Three shapes depending on whether the file existed at HEAD:
          * untracked (never in git): `git clean` deletes the worktree copy.
          * added-in-index (new in index, not in HEAD): unstage, then clean
            the now-untracked worktree copy.
          * everything else (file existed at HEAD with changes): a single
            `git restore --source=HEAD --staged --worktree` overwrites both
            the index and worktree entries from HEAD.

        For submodule entries, each argv is prefixed with ``-C <cwd>`` and
        uses the submodule-relative filename so the dialog matches what
        runs.
        """
        cwd, name = self._entry_target(entry)
        prefix = ["git", "-C", cwd] if entry.submodule else ["git"]
        code = entry.code
        if code.is_untracked:
            return [prefix + ["clean", "-f", "--", name]]
        if code.staged == GitStatus.ADDED:
            return [
                prefix + ["restore", "--staged", "--", name],
                prefix + ["clean", "-f", "--", name],
            ]
        return [
            prefix
            + [
                "restore",
                "--source=HEAD",
                "--staged",
                "--worktree",
                "--",
                name,
            ]
        ]

    def restore_file(self, entry: GitEntry) -> list[subprocess.CompletedProcess[str]]:
        """Run `restore_commands(entry)` in order, stopping on first failure.

        Returned list holds every CompletedProcess that was actually run, so
        the caller can inspect stderr from the failing step.
        """
        cwd, _ = self._entry_target(entry)
        results: list[subprocess.CompletedProcess[str]] = []
        for argv in self.restore_commands(entry):
            args = argv[3:] if argv[1:3] == ["-C", cwd] else argv[1:]
            result = self._run_in(cwd, *args)
            results.append(result)
            if result.returncode != 0:
                break
        return results

    def delete_commands(self, entry: GitEntry) -> list[list[str]]:
        """Return the argv(s) that DELETE would run for *entry*.

        Operations are determined entirely by the entry's status code, so
        callers can group entries by code and display one command list per
        group. Four shapes:
          * untracked (`??`): `git clean -f` removes the worktree copy.
          * added-in-index (`A_`): unstage the index entry, then clean the
            worktree copy.
          * unstaged delete (` D`): stage the deletion via `git rm --cached`
            (the worktree copy is already gone, so a plain `git rm` would
            fail).
          * everything else tracked: `git rm -f` removes the worktree copy
            and stages the deletion in one step.

        Submodule entries are prefixed with ``-C <cwd>`` and use the
        submodule-relative filename.
        """
        cwd, name = self._entry_target(entry)
        prefix = ["git", "-C", cwd] if entry.submodule else ["git"]
        code = entry.code
        if code.is_untracked:
            return [prefix + ["clean", "-f", "--", name]]
        if code.staged == GitStatus.ADDED:
            return [
                prefix + ["rm", "-f", "--cached", "--", name],
                prefix + ["clean", "-f", "--", name],
            ]
        if code.unstaged == GitStatus.DELETED:
            return [prefix + ["rm", "--cached", "--", name]]
        return [prefix + ["rm", "-f", "--", name]]

    def delete_file(self, entry: GitEntry) -> list[subprocess.CompletedProcess[str]]:
        """Run `delete_commands(entry)` in order, stopping on first failure."""
        cwd, _ = self._entry_target(entry)
        results: list[subprocess.CompletedProcess[str]] = []
        for argv in self.delete_commands(entry):
            args = argv[3:] if argv[1:3] == ["-C", cwd] else argv[1:]
            result = self._run_in(cwd, *args)
            results.append(result)
            if result.returncode != 0:
                break
        return results

    # ------------------------------------------------------------------
    # Stash
    # ------------------------------------------------------------------

    def stash_command(self, *, filenames: list[str] | None = None) -> list[str]:
        """Argv for :meth:`stash` (for display/confirmation).

        `--include-untracked` because the file list the user is looking at
        shows untracked files: a stash that left them behind would clear only
        part of what they just asked to put away. Ignored files stay put —
        that needs `--all`, which this never passes.

        A pathspec limits the stash to *filenames*; without one the whole
        worktree goes. Submodules are not recursed into either way, which is
        git's own behaviour.
        """
        argv = ["git", "stash", "push", "--include-untracked"]
        if filenames:
            argv += ["--", *filenames]
        return argv

    def stash(self, *, filenames: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        """Run `git stash push`, optionally limited to *filenames*."""
        return self._run(*self.stash_command(filenames=filenames)[1:])

    def stash_entries(self) -> list[str]:
        """`git stash list` lines, newest first; empty when there is no stash."""
        result = self._run("stash", "list")
        return [line for line in (result.stdout or "").splitlines() if line.strip()]

    def stash_pop_command(self) -> list[str]:
        """Argv for :meth:`stash_pop` (for display/confirmation)."""
        return ["git", "stash", "pop"]

    def stash_pop(self) -> subprocess.CompletedProcess[str]:
        """Run `git stash pop` — reapply the newest stash entry and drop it."""
        return self._run(*self.stash_pop_command()[1:])

    # ------------------------------------------------------------------
    # Remote
    # ------------------------------------------------------------------

    def remote_names(self) -> list[str]:
        """Configured remotes, in git's own order (`origin` first, normally)."""
        result = self._run("remote")
        return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]

    def upstream_branch(self) -> str | None:
        """The current branch's upstream (`origin/master`), or None if unset."""
        result = self._run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        if result.returncode != 0:
            return None
        name = (result.stdout or "").strip()
        return name or None

    def pull_command(self) -> list[str]:
        """Argv for :meth:`pull` (for display/confirmation).

        `--ff-only` because a pull that has to merge leaves the repo in a
        state this app can't show or finish: a conflicted merge, or an editor
        waiting on a merge message in a terminal the TUI is sitting on.
        Refusing is recoverable — the failure names the divergence, and
        `Ctrl+O` puts a shell one keystroke away.
        """
        return ["git", "pull", "--ff-only"]

    def pull(self) -> subprocess.CompletedProcess[str]:
        """Run `git pull --ff-only`."""
        return self._run(*self.pull_command()[1:])

    def push_command(self) -> list[str]:
        """Argv for :meth:`push` (for display/confirmation).

        A branch with an upstream is a plain `git push`. One without needs the
        `--set-upstream` form spelled out, because that push creates a branch
        on the remote — the confirmation is the place to say so, and a bare
        `git push` would only fail with git's own suggestion to type this.
        """
        if self.upstream_branch() is not None:
            return ["git", "push"]
        remotes = self.remote_names()
        branch = self.branch_name()
        if remotes and branch:
            return ["git", "push", "--set-upstream", remotes[0], branch]
        return ["git", "push"]

    def push(self) -> subprocess.CompletedProcess[str]:
        """Run whatever :meth:`push_command` describes."""
        return self._run(*self.push_command()[1:])
