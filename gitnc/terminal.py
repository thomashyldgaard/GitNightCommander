"""Terminal screen session management and git display helpers."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping

from .git import GIT, GitCode, GitEntry, GitFilelist, GitStatus

PREVIOUS_SCREEN_TOGGLE_KEY = "\x0f"

# Midnight Commander exports `MC_SID` into the subshell it runs commands in,
# and `MC_TMPDIR` into its own environment, which a command started with the
# subshell disabled (`mc -u`) inherits. Either one means mc is our ancestor.
MIDNIGHT_COMMANDER_ENV_VARS = ("MC_SID", "MC_TMPDIR")


def started_from_midnight_commander(environ: Mapping[str, str] | None = None) -> bool:
    """Whether the process runs under Midnight Commander.

    Under mc's subshell the keyboard doesn't reach us directly: mc reads the
    terminal and forwards the keys to the subshell's pty, and it keeps its own
    `Ctrl+O` — the key that toggles our previous screen — to switch back to
    its panels, leaving this app running out of sight.
    """
    env = os.environ if environ is None else environ
    return any(env.get(name) for name in MIDNIGHT_COMMANDER_ENV_VARS)


class Terminal:
    """Utility class for terminal screen management and git display helpers."""

    def load_commits(self, path: str = ".") -> list:
        return GIT(path).load_commits()

    def load_file_diff(self, path: str, entry: GitEntry) -> str:
        return GIT(path).load_file_diff(entry)

    def load_status(self, path: str = ".") -> GitFilelist:
        return GIT(path).load_status()

    def status_markup(self, code: GitCode, filename: str) -> str:
        label = code.value
        if code.is_untracked:
            color = "dim"
        elif code.contains(GitStatus.ADDED):
            color = "green"
        elif code.contains(GitStatus.DELETED):
            color = "red"
        elif code.contains(GitStatus.RENAMED):
            color = "cyan"
        else:
            color = "yellow"
        return f"[{color}]{label}[/{color}]  {filename}"

    def _wait_for_toggle_key(
        self, read_key: Callable[[], str], toggle_key: str = PREVIOUS_SCREEN_TOGGLE_KEY
    ) -> None:
        while read_key() != toggle_key:
            pass

    def _read_key_posix(self) -> str:
        if not sys.stdin.isatty():
            raise OSError("stdin is not a tty")

        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                key = os.read(fd, 1)
                if key:
                    return key.decode(errors="ignore")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

    def _read_key_windows(self) -> str:
        # Only reached when os.name == "nt"; the assert tells the type checker so,
        # since msvcrt's stubs are Windows-only.
        assert sys.platform == "win32"
        import msvcrt

        getwch = msvcrt.getwch
        while True:
            key = getwch()
            if key in ("\x00", "\xe0"):
                getwch()
                continue
            return key

    def wait_for_previous_screen_toggle(self) -> None:
        read_key = self._read_key_windows if os.name == "nt" else self._read_key_posix
        self._wait_for_toggle_key(read_key)

    def write_previous_screen(self, text: str) -> None:
        """Write `text` to the terminal the TUI was started from.

        Only meaningful while the app is suspended: Textual has left the
        alternate screen buffer by then, so the text lands on the previous
        screen and stays in its scrollback — which is what makes it readable
        again later, when `Ctrl+O` puts a shell on that same screen.

        `sys.stdout` is read per call rather than captured, because
        `App.suspend()` rebinds it to the real stdout for the length of the
        block. A closed or redirected stream isn't worth failing the caller
        over, so the write is best-effort.
        """
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass

    def previous_screen_shell_command(self) -> list[str]:
        env_var = "COMSPEC" if os.name == "nt" else "SHELL"
        raw_shell = os.environ.get(env_var) or ("cmd.exe" if os.name == "nt" else "/bin/sh")
        argv = shlex.split(raw_shell, posix=os.name != "nt")
        if not argv:
            raise OSError(f"{env_var} does not define a shell")
        argv[0] = shutil.which(argv[0]) or argv[0]
        if os.name != "nt" and "-i" not in argv[1:]:
            argv.append("-i")
        return argv

    def _terminate_previous_screen_shell(self, pid: int) -> None:
        import signal
        import time

        signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL)
        for sig in signals:
            try:
                os.killpg(pid, sig)
            except ProcessLookupError:
                break

            deadline = time.monotonic() + 0.2
            while time.monotonic() < deadline:
                waited_pid, _ = os.waitpid(pid, os.WNOHANG)
                if waited_pid == pid:
                    return
                time.sleep(0.01)

        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def _run_previous_screen_shell_posix(
        self, toggle_key: str = PREVIOUS_SCREEN_TOGGLE_KEY
    ) -> None:
        import fcntl
        import pty
        import select
        import termios
        import tty

        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise OSError("stdin/stdout are not tty devices")

        argv = self.previous_screen_shell_command()
        pid, master_fd = pty.fork()
        if pid == 0:
            try:
                os.execvpe(argv[0], argv, os.environ.copy())
            except OSError as exc:
                print(f"Unable to launch shell: {exc}", file=sys.stderr)
            os._exit(1)

        stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()
        saved = termios.tcgetattr(stdin_fd)
        toggle = toggle_key.encode()
        toggled = False

        try:
            try:
                window_size = fcntl.ioctl(stdin_fd, termios.TIOCGWINSZ, b"\x00" * 8)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, window_size)
            except OSError:
                pass

            tty.setraw(stdin_fd)
            while True:
                ready, _, _ = select.select([stdin_fd, master_fd], [], [])
                if stdin_fd in ready:
                    try:
                        data = os.read(stdin_fd, 1024)
                    except OSError:
                        break
                    if not data:
                        break
                    toggle_at = data.find(toggle)
                    if toggle_at != -1:
                        if toggle_at:
                            os.write(master_fd, data[:toggle_at])
                        toggled = True
                        break
                    os.write(master_fd, data)
                if master_fd in ready:
                    try:
                        output = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not output:
                        break
                    os.write(stdout_fd, output)
        finally:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved)
            os.close(master_fd)

        if toggled:
            self._terminate_previous_screen_shell(pid)
            return

        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def run_previous_screen_session(self) -> None:
        if os.name == "nt":
            self.wait_for_previous_screen_toggle()
            return
        self._run_previous_screen_shell_posix()
