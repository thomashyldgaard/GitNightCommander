"""A stand-in for the git processes `GIT._run_in` spawns.

`_run_in` builds its `CompletedProcess` from `Popen` + `communicate()` rather
than from `subprocess.run()`, so that a quit can terminate a read that is
still running (see `GIT.shutdown()`). Tests patch the same seam one level
down: `fake_git_processes()` replaces `Popen` and hands each call whatever the
test asked for, while recording the argv it was asked to run.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch


class FakeGitProcesses:
    """Callable stand-in for `subprocess.Popen`, one call per git command."""

    def __init__(
        self,
        *,
        answer: tuple[int, str, str],
        results: list[tuple[int, str, str]] | None,
    ) -> None:
        # *results* is (returncode, stdout, stderr) per call, in order, for a
        # test about a sequence of commands; once it runs out — and for every
        # test that isn't about one — *answer* is what each call returns.
        self._results = list(results or [])
        self._answer = answer
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], **_kwargs: object) -> MagicMock:
        self.commands.append(list(argv))
        returncode, stdout, stderr = self._results.pop(0) if self._results else self._answer
        process = MagicMock()
        process.communicate.return_value = (stdout, stderr)
        process.returncode = returncode
        return process

    @property
    def call_count(self) -> int:
        return len(self.commands)


@contextmanager
def fake_git_processes(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    results: list[tuple[int, str, str]] | None = None,
):
    """Patch `Popen` for the duration of the block, yielding the fake."""
    fake = FakeGitProcesses(answer=(returncode, stdout, stderr), results=results)
    with patch("gitnc.git.subprocess.Popen", new=fake):
        yield fake
