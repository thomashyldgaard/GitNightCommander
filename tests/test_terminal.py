import io
import unittest
from unittest.mock import MagicMock, patch

from gitnc.git import Commit
from gitnc.terminal import (
    PREVIOUS_SCREEN_TOGGLE_KEY,
    Terminal,
    started_from_midnight_commander,
)
from tests.gitprocess import fake_git_processes


class TestTerminalLoadCommits(unittest.TestCase):
    def _make_result(self, stdout):
        m = MagicMock()
        m.stdout = stdout
        return m

    def test_parses_single_commit(self):
        fake = "abc123\x1fAlice\x1f2024-01-01\x1fFix bug"
        with fake_git_processes(stdout=fake):
            commits = Terminal().load_commits()
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0], Commit("abc123", "Alice", "2024-01-01", "Fix bug"))

    def test_parses_multiple_commits(self):
        lines = "aaa\x1fAlice\x1f2024-01-01\x1fFirst\nbbb\x1fBob\x1f2024-01-02\x1fSecond"
        with fake_git_processes(stdout=lines):
            commits = Terminal().load_commits()
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[1].author, "Bob")

    def test_skips_malformed_lines(self):
        fake = "bad line\nabc\x1fAlice\x1f2024-01-01\x1fGood"
        with fake_git_processes(stdout=fake):
            commits = Terminal().load_commits()
        self.assertEqual(len(commits), 1)

    def test_empty_output_returns_empty_list(self):
        with fake_git_processes():
            commits = Terminal().load_commits()
        self.assertEqual(commits, [])

    def test_subject_with_delimiter_is_preserved(self):
        fake = "abc\x1fAlice\x1f2024-01-01\x1fSubject\x1fwith delimiter"
        with fake_git_processes(stdout=fake):
            commits = Terminal().load_commits()
        self.assertEqual(commits[0].subject, "Subject\x1fwith delimiter")


class TestTerminalPreviousTerminal(unittest.TestCase):
    def test_wait_for_toggle_key_ignores_other_keys(self):
        seen = []
        keys = iter(["a", "\n", PREVIOUS_SCREEN_TOGGLE_KEY])

        def read_key():
            key = next(keys)
            seen.append(key)
            return key

        Terminal()._wait_for_toggle_key(read_key)
        self.assertEqual(seen, ["a", "\n", PREVIOUS_SCREEN_TOGGLE_KEY])

    def test_previous_screen_shell_command_uses_shell_env(self):
        with patch.dict("os.environ", {"SHELL": "/bin/bash"}, clear=False):
            command = Terminal().previous_screen_shell_command()
        self.assertEqual(command, ["/bin/bash", "-i"])

    def test_write_previous_screen_goes_to_the_current_stdout(self):
        """Read per call, not captured: `App.suspend()` rebinds `sys.stdout`
        to the real one for the length of the block, which is the only time
        this writes anything."""
        stream = io.StringIO()
        with patch("gitnc.terminal.sys.stdout", stream):
            Terminal().write_previous_screen("drafting\n")
        self.assertEqual(stream.getvalue(), "drafting\n")

    def test_write_previous_screen_survives_a_closed_stream(self):
        """A commit is not worth failing over a stdout that has gone away."""
        stream = io.StringIO()
        stream.close()
        with patch("gitnc.terminal.sys.stdout", stream):
            Terminal().write_previous_screen("drafting\n")

    def test_run_previous_screen_session_falls_back_to_wait_on_windows(self):
        with (
            patch("gitnc.terminal.os.name", "nt"),
            patch.object(Terminal, "wait_for_previous_screen_toggle") as wait_for_toggle,
        ):
            Terminal().run_previous_screen_session()
        wait_for_toggle.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()


class TestStartedFromMidnightCommander(unittest.TestCase):
    def test_false_without_mc_variables(self):
        self.assertFalse(started_from_midnight_commander(environ={"SHELL": "/bin/bash"}))

    def test_true_under_mc_subshell(self):
        self.assertTrue(started_from_midnight_commander(environ={"MC_SID": "4242"}))

    def test_true_when_started_without_subshell(self):
        self.assertTrue(started_from_midnight_commander(environ={"MC_TMPDIR": "/tmp/mc-user"}))

    def test_empty_value_does_not_count(self):
        self.assertFalse(started_from_midnight_commander(environ={"MC_SID": ""}))

    def test_reads_process_environment_by_default(self):
        with patch.dict("os.environ", {"MC_SID": "4242"}):
            self.assertTrue(started_from_midnight_commander())
