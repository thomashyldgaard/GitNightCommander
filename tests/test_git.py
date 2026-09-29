import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gitnc.git import (
    DEFAULT_STATUS_WIDTH,
    GIT,
    GitCode,
    GitEntry,
    GitFilelist,
    GitStatus,
    _entry_stat,
)
from tests.gitprocess import fake_git_processes


class TestGitStatus(unittest.TestCase):
    def _make_result(self, stdout):
        result = MagicMock()
        result.stdout = stdout
        return result

    def test_load_status_returns_git_filelist_with_enum_codes(self):
        stdout = "M  tracked.py\n?? new.txt\n"
        with fake_git_processes(stdout=stdout):
            entries = GIT().load_status()

        self.assertIsInstance(entries, GitFilelist)
        self.assertEqual(
            entries,
            GitFilelist(
                [
                    GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt"),
                    GitEntry(GitCode.MODIFIED_UNMODIFIED, "tracked.py"),
                ]
            ),
        )
        self.assertIs(entries[1].code.staged, GitStatus.MODIFIED)
        self.assertIs(entries[1].code.unstaged, GitStatus.UNMODIFIED)

    def test_load_status_lists_every_untracked_file_by_default(self):
        with fake_git_processes() as git:
            GIT().load_status()
        self.assertIn("--untracked-files=all", git.commands[0])

    def test_load_status_can_collapse_untracked_directories(self):
        """Git decides which directories collapse: `normal` folds only a
        directory with nothing tracked in it, reported with a trailing `/`."""
        with fake_git_processes(stdout="?? vendor/\n M app.py\n") as git:
            entries = GIT().load_status(collapse_untracked_dirs=True)
        self.assertIn("--untracked-files=normal", git.commands[0])
        self.assertEqual(
            [e.filename for e in entries],
            ["app.py", "vendor/"],
        )

    def test_index_of_falls_back_to_the_directory_a_file_collapsed_into(self):
        filelist = GitFilelist(
            [
                GitEntry(GitCode.MODIFIED_UNMODIFIED, "app.py"),
                GitEntry(GitCode.UNTRACKED_UNTRACKED, "vendor/"),
            ]
        )
        self.assertEqual(
            filelist.index_of(GitEntry(GitCode.UNTRACKED_UNTRACKED, "vendor/lib/a.py")), 1
        )
        self.assertIsNone(filelist.index_of(GitEntry(GitCode.UNTRACKED_UNTRACKED, "vendors.py")))

    def test_collapsed_directory_shows_a_dir_marker_for_its_size(self):
        with tempfile.TemporaryDirectory() as root:
            os.mkdir(os.path.join(root, "vendor"))
            size, _ = _entry_stat(root, "vendor/", "%Y")
        self.assertEqual(size, "<DIR>")

    def test_collapsed_directory_content_lists_the_files_below_it(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "vendor", "lib"))
            os.makedirs(os.path.join(root, "vendor", ".git"))
            for name in ("vendor/b.txt", "vendor/lib/a.py", "vendor/.git/HEAD"):
                with open(os.path.join(root, name), "w") as fh:
                    fh.write("x")
            text = GIT(root).load_file_content(GitEntry(GitCode.UNTRACKED_UNTRACKED, "vendor/"))
        self.assertEqual(
            text.splitlines(),
            ["Untracked directory: vendor/ (2 file(s))", "", "b.txt", os.path.join("lib", "a.py")],
        )

    def test_git_filelist_is_the_view_model_for_short_and_long_lists(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        filelist = GitFilelist([entry])

        with patch("gitnc.git._entry_stat", return_value=("42B", "now")):
            short_row = filelist.row_texts(
                ".",
                status_width=DEFAULT_STATUS_WIDTH,
                name_width=6,
                size_width=10,
                mtime_width=16,
            )[0]
            long_row = filelist.row_texts(
                ".",
                status_width=DEFAULT_STATUS_WIDTH,
                name_width=20,
                size_width=10,
                mtime_width=16,
            )[0]

        self.assertEqual(filelist.status_message(), "1 file(s) changed")
        self.assertEqual(
            GitFilelist().status_message(),
            "Nothing to commit, working tree clean",
        )
        self.assertNotIn(entry.filename, short_row)
        self.assertIn(entry.filename, long_row)
        self.assertTrue(short_row.startswith("[bold yellow]M[/bold yellow]       "))
        self.assertTrue(long_row.startswith("[bold yellow]M[/bold yellow]       "))
        self.assertTrue(short_row.endswith(f"{'42B':>10}  {'now':>16}"))
        self.assertTrue(long_row.endswith(f"{'42B':>10}  {'now':>16}"))
        self.assertIn(f"{entry.filename:<20}  {'42B':>10}", long_row)

    def test_git_filelist_tracks_highlighted_entry(self):
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/first.py")
        second = GitEntry(GitCode.UNTRACKED_UNTRACKED, "pkg/second.py")
        filelist = GitFilelist([first, second])

        self.assertIsNone(filelist.highlighted_entry)
        self.assertEqual(filelist.set_highlighted_index(1), second)
        self.assertEqual(filelist.highlighted_entry, second)
        self.assertIsNone(filelist.set_highlighted_index(9))
        self.assertIsNone(filelist.highlighted_entry)

    def test_git_filelist_sorts_entries_alphabetically_by_full_filename(self):
        zed = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/zed.py")
        alpha_nested = GitEntry(GitCode.MODIFIED_UNMODIFIED, "src/alpha.py")
        alpha_root = GitEntry(GitCode.MODIFIED_UNMODIFIED, "alpha.py")
        beta = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/Beta.py")

        filelist = GitFilelist([zed, alpha_nested, alpha_root, beta])

        self.assertEqual(
            [entry.filename for entry in filelist],
            ["alpha.py", "pkg/Beta.py", "pkg/zed.py", "src/alpha.py"],
        )

    def test_load_file_diff_returns_untracked_message_for_enum_code(self):
        entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")
        with fake_git_processes():
            diff = GIT().load_file_diff(entry)

        self.assertEqual(diff, "Untracked file: new.txt")

    def test_load_file_content_returns_text_of_untracked_file(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "new.txt"), "w") as fh:
                fh.write("line one\nline two\n")
            entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "new.txt")

            content = GIT(tmp).load_file_content(entry)

        self.assertEqual(content, "line one\nline two\n")

    def test_load_file_content_flags_binary_files(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "bin.dat"), "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n\x00\x00")
            entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "bin.dat")

            content = GIT(tmp).load_file_content(entry)

        self.assertEqual(content, "Binary file: bin.dat")

    def test_load_file_content_returns_error_message_when_missing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "gone.txt")
            content = GIT(tmp).load_file_content(entry)

        self.assertTrue(content.startswith("Cannot read file: gone.txt"))

    def test_toggle_selection_marks_and_unmarks_entries(self):
        first = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")
        second = GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/b.py")
        filelist = GitFilelist([first, second])

        self.assertFalse(filelist.is_selected(0))
        self.assertEqual(filelist.toggle_selection(0), first)
        self.assertTrue(filelist.is_selected(0))
        self.assertEqual(filelist.selected_entries(), [first])

        filelist.toggle_selection(1)
        self.assertEqual(filelist.selected_entries(), [first, second])

        filelist.toggle_selection(0)
        self.assertFalse(filelist.is_selected(0))
        self.assertEqual(filelist.selected_entries(), [second])

    def test_toggle_selection_ignores_out_of_range_index(self):
        filelist = GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "a.py")])
        self.assertIsNone(filelist.toggle_selection(5))
        self.assertIsNone(filelist.toggle_selection(None))
        self.assertEqual(filelist.selected_filenames, set())

    def test_restore_selections_drops_files_that_no_longer_exist(self):
        filelist = GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "keeps.py")])
        filelist.restore_selections({"keeps.py", "gone.py"})
        self.assertEqual(filelist.selected_filenames, {"keeps.py"})

    def test_index_of_falls_back_to_filename_when_status_code_changes(self):
        entry = GitEntry(GitCode.UNMODIFIED_MODIFIED, "pkg/a.py")
        filelist = GitFilelist([GitEntry(GitCode.MODIFIED_UNMODIFIED, "pkg/a.py")])

        self.assertEqual(filelist.index_of(entry), 0)

    def test_clear_selections_empties_the_set(self):
        entry = GitEntry(GitCode.MODIFIED_UNMODIFIED, "a.py")
        filelist = GitFilelist([entry])
        filelist.toggle_selection(0)
        filelist.clear_selections()
        self.assertEqual(filelist.selected_filenames, set())

    def test_has_staged_and_unstaged_change_flags(self):
        self.assertTrue(GitCode.MODIFIED_UNMODIFIED.has_staged_changes)
        self.assertFalse(GitCode.MODIFIED_UNMODIFIED.has_unstaged_changes)
        self.assertFalse(GitCode.UNMODIFIED_MODIFIED.has_staged_changes)
        self.assertTrue(GitCode.UNMODIFIED_MODIFIED.has_unstaged_changes)
        self.assertTrue(GitCode.MODIFIED_MODIFIED.has_staged_changes)
        self.assertTrue(GitCode.MODIFIED_MODIFIED.has_unstaged_changes)
        self.assertFalse(GitCode.UNTRACKED_UNTRACKED.has_staged_changes)
        self.assertTrue(GitCode.UNTRACKED_UNTRACKED.has_unstaged_changes)
        self.assertTrue(GitCode.ADDED_UNMODIFIED.has_staged_changes)
        self.assertFalse(GitCode.ADDED_UNMODIFIED.has_unstaged_changes)
        self.assertTrue(GitCode.UNMODIFIED_DELETED.has_unstaged_changes)
        self.assertFalse(GitCode.UNMODIFIED_DELETED.has_staged_changes)

    def test_stage_and_unstage_command_argv_are_plumbing_safe(self):
        """The argv displayed in the popup must match what _run actually invokes
        (git, -C <path>, then the action). stage uses `add --`; unstage uses
        `restore --staged --`; both pass -- so filenames beginning with `-`
        aren't parsed as flags."""
        git = GIT("/tmp/repo")
        self.assertEqual(git.stage_command("foo bar.py"), ["git", "add", "--", "foo bar.py"])
        self.assertEqual(
            git.unstage_command("foo bar.py"),
            ["git", "restore", "--staged", "--", "foo bar.py"],
        )

    def test_stage_file_shells_out_to_git_add(self):
        with fake_git_processes() as git:
            GIT("/tmp/repo").stage_file("a.py")
        self.assertEqual(
            git.commands,
            [["git", "-c", "color.ui=false", "-C", "/tmp/repo", "add", "--", "a.py"]],
        )

    def test_unstage_file_shells_out_to_git_restore_staged(self):
        with fake_git_processes() as git:
            GIT("/tmp/repo").unstage_file("a.py")
        self.assertEqual(
            git.commands,
            [
                [
                    "git",
                    "-c",
                    "color.ui=false",
                    "-C",
                    "/tmp/repo",
                    "restore",
                    "--staged",
                    "--",
                    "a.py",
                ]
            ],
        )

    def test_every_command_asks_git_for_uncolored_output(self):
        """The UI prints git's stdout literally, so colored output would show
        up as raw escape sequences."""
        with fake_git_processes() as git:
            GIT("/tmp/repo").show_commit("cafe123")
        self.assertEqual(git.commands[0][:3], ["git", "-c", "color.ui=false"])

    def test_color_escapes_are_stripped_from_stdout(self):
        """`color.diff = always` in the user's config overrides `color.ui`,
        so escapes that still come through are removed before the UI sees
        them."""
        colored = "\x1b[1mcommit cafe123\x1b[m\n\x1b[32m+added\x1b[m\n"
        with fake_git_processes(stdout=colored):
            detail = GIT("/tmp/repo").show_commit("cafe123")

        self.assertEqual(detail, "commit cafe123\n+added\n")

    def test_is_restorable_covers_every_actionable_git_status(self):
        """Restore should apply to any entry with changes relative to HEAD
        except ignored files and unmerged conflicts. Unmodified files aren't
        shown in the status list, so is_restorable's value on them is moot —
        but it defaults to False for completeness."""
        restorable = [
            GitCode.MODIFIED_UNMODIFIED,
            GitCode.UNMODIFIED_MODIFIED,
            GitCode.MODIFIED_MODIFIED,
            GitCode.ADDED_UNMODIFIED,
            GitCode.ADDED_MODIFIED,
            GitCode.UNMODIFIED_DELETED,
            GitCode.DELETED_UNMODIFIED,
            GitCode.RENAMED_UNMODIFIED,
            GitCode.TYPE_CHANGED_UNMODIFIED,
            GitCode.UNTRACKED_UNTRACKED,
        ]
        for code in restorable:
            with self.subTest(code=code.name):
                self.assertTrue(code.is_restorable, code.name)

        not_restorable = [
            GitCode.IGNORED_IGNORED,
            GitCode.UPDATED_UNMERGED_UPDATED_UNMERGED,
            GitCode.UPDATED_UNMERGED_ADDED,
            GitCode.ADDED_UPDATED_UNMERGED,
            GitCode.UNMODIFIED_UNMODIFIED,
        ]
        for code in not_restorable:
            with self.subTest(code=code.name):
                self.assertFalse(code.is_restorable, code.name)

    def test_restore_commands_for_modified_file_resets_index_and_worktree(self):
        """A modified-only file (staged, unstaged, or both) was in HEAD, so
        a single `git restore --source=HEAD --staged --worktree` puts both
        the index and working-tree copies back to HEAD."""
        entry = GitEntry(GitCode.MODIFIED_MODIFIED, "pkg/a.py")
        self.assertEqual(
            GIT().restore_commands(entry),
            [
                [
                    "git",
                    "restore",
                    "--source=HEAD",
                    "--staged",
                    "--worktree",
                    "--",
                    "pkg/a.py",
                ]
            ],
        )

    def test_restore_commands_for_deleted_file_also_uses_restore_source_head(self):
        """A deleted (but-tracked) file exists in HEAD, so the same
        restore-from-HEAD form brings it back."""
        entry = GitEntry(GitCode.UNMODIFIED_DELETED, "pkg/gone.py")
        self.assertEqual(
            GIT().restore_commands(entry),
            [
                [
                    "git",
                    "restore",
                    "--source=HEAD",
                    "--staged",
                    "--worktree",
                    "--",
                    "pkg/gone.py",
                ]
            ],
        )

    def test_restore_commands_for_added_file_unstages_and_cleans(self):
        """An added-in-index file is new to git — HEAD has no copy to
        restore from — so we unstage (making it untracked) and then remove
        the worktree copy with `git clean -f`."""
        entry = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        self.assertEqual(
            GIT().restore_commands(entry),
            [
                ["git", "restore", "--staged", "--", "pkg/new.py"],
                ["git", "clean", "-f", "--", "pkg/new.py"],
            ],
        )

    def test_restore_commands_for_untracked_file_only_cleans(self):
        entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "scratch.txt")
        self.assertEqual(
            GIT().restore_commands(entry),
            [["git", "clean", "-f", "--", "scratch.txt"]],
        )

    def test_restore_file_runs_each_command_and_stops_on_first_failure(self):
        """The added-in-index path issues two commands. If `git restore
        --staged` fails, `git clean` must NOT run — otherwise we'd delete
        a file the user still has staged."""
        entry = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        with fake_git_processes(results=[(1, "", "oops"), (0, "", "")]) as git:
            results = GIT("/tmp/repo").restore_file(entry)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].returncode, 1)
        self.assertEqual(
            git.commands,
            [
                [
                    "git",
                    "-c",
                    "color.ui=false",
                    "-C",
                    "/tmp/repo",
                    "restore",
                    "--staged",
                    "--",
                    "pkg/new.py",
                ]
            ],
        )

    def test_restore_file_runs_full_sequence_on_success(self):
        entry = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        with fake_git_processes() as git:
            results = GIT("/tmp/repo").restore_file(entry)

        self.assertEqual(len(results), 2)
        self.assertEqual(git.call_count, 2)
        self.assertEqual(
            git.commands,
            [
                [
                    "git",
                    "-c",
                    "color.ui=false",
                    "-C",
                    "/tmp/repo",
                    "restore",
                    "--staged",
                    "--",
                    "pkg/new.py",
                ],
                [
                    "git",
                    "-c",
                    "color.ui=false",
                    "-C",
                    "/tmp/repo",
                    "clean",
                    "-f",
                    "--",
                    "pkg/new.py",
                ],
            ],
        )

    def test_is_deletable_skips_ignored_unmerged_and_completed_deletes(self):
        """Delete is meaningful for any tracked or untracked entry, but
        skips ignored files, unmerged conflicts, and entries whose
        worktree copy is already gone with no further index work to do
        (`D ` and `DD`)."""
        deletable = [
            GitCode.MODIFIED_UNMODIFIED,
            GitCode.UNMODIFIED_MODIFIED,
            GitCode.MODIFIED_MODIFIED,
            GitCode.ADDED_UNMODIFIED,
            GitCode.ADDED_MODIFIED,
            GitCode.UNMODIFIED_DELETED,
            GitCode.MODIFIED_DELETED,
            GitCode.RENAMED_UNMODIFIED,
            GitCode.TYPE_CHANGED_UNMODIFIED,
            GitCode.UNTRACKED_UNTRACKED,
        ]
        for code in deletable:
            with self.subTest(code=code.name):
                self.assertTrue(code.is_deletable, code.name)

        not_deletable = [
            GitCode.IGNORED_IGNORED,
            GitCode.UPDATED_UNMERGED_UPDATED_UNMERGED,
            GitCode.UPDATED_UNMERGED_ADDED,
            GitCode.ADDED_UPDATED_UNMERGED,
            GitCode.DELETED_UNMODIFIED,
            GitCode.DELETED_DELETED,
        ]
        for code in not_deletable:
            with self.subTest(code=code.name):
                self.assertFalse(code.is_deletable, code.name)

    def test_delete_commands_for_untracked_returns_git_clean(self):
        entry = GitEntry(GitCode.UNTRACKED_UNTRACKED, "scratch.txt")
        self.assertEqual(
            GIT().delete_commands(entry),
            [["git", "clean", "-f", "--", "scratch.txt"]],
        )

    def test_delete_commands_for_added_unstages_then_cleans(self):
        """Added-in-index files have no HEAD copy, so to delete we unstage
        the index entry then clean the now-untracked worktree copy."""
        entry = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        self.assertEqual(
            GIT().delete_commands(entry),
            [
                ["git", "rm", "-f", "--cached", "--", "pkg/new.py"],
                ["git", "clean", "-f", "--", "pkg/new.py"],
            ],
        )

    def test_delete_commands_for_unstaged_delete_stages_the_removal(self):
        """The worktree copy is already gone, so a plain `git rm` would
        fail. Use --cached to stage the deletion in the index."""
        entry = GitEntry(GitCode.UNMODIFIED_DELETED, "pkg/gone.py")
        self.assertEqual(
            GIT().delete_commands(entry),
            [["git", "rm", "--cached", "--", "pkg/gone.py"]],
        )

    def test_delete_commands_for_modified_uses_git_rm_force(self):
        entry = GitEntry(GitCode.MODIFIED_MODIFIED, "pkg/a.py")
        self.assertEqual(
            GIT().delete_commands(entry),
            [["git", "rm", "-f", "--", "pkg/a.py"]],
        )

    def test_delete_file_runs_each_command_and_stops_on_first_failure(self):
        entry = GitEntry(GitCode.ADDED_UNMODIFIED, "pkg/new.py")
        with fake_git_processes(results=[(1, "", "oops"), (0, "", "")]) as git:
            results = GIT("/tmp/repo").delete_file(entry)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].returncode, 1)
        self.assertEqual(
            git.commands,
            [
                [
                    "git",
                    "-c",
                    "color.ui=false",
                    "-C",
                    "/tmp/repo",
                    "rm",
                    "-f",
                    "--cached",
                    "--",
                    "pkg/new.py",
                ]
            ],
        )

    def test_submodule_branch_mismatches_returns_empty_when_no_submodules(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            git = GIT(tmp)
            with patch.object(git, "_run") as run:
                run.return_value = MagicMock(returncode=0, stdout="main\n", stderr="")
                self.assertEqual(git.submodule_branch_mismatches(), [])
            self.assertFalse(os.path.exists(os.path.join(tmp, ".gitmodules")))

    def test_submodule_branch_mismatches_reports_each_initialized_submodule_on_other_branch(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            sub_a = os.path.join(tmp, "sub_a")
            sub_b = os.path.join(tmp, "sub_b")
            sub_skip = os.path.join(tmp, "sub_skip")
            for sub in (sub_a, sub_b, sub_skip):
                os.makedirs(sub)
            for sub in (sub_a, sub_b):
                open(os.path.join(sub, ".git"), "w").close()
            with open(os.path.join(tmp, ".gitmodules"), "w") as fh:
                fh.write("ignored\n")

            git = GIT(tmp)

            def fake_run_in(cwd, *args):
                if args == ("branch", "--show-current"):
                    if cwd == tmp:
                        return MagicMock(stdout="main\n", stderr="", returncode=0)
                    if cwd == sub_a:
                        return MagicMock(stdout="dev\n", stderr="", returncode=0)
                    if cwd == sub_b:
                        return MagicMock(stdout="main\n", stderr="", returncode=0)
                if args[:3] == ("config", "--file", ".gitmodules"):
                    return MagicMock(
                        stdout=(
                            "submodule.a.path sub_a\n"
                            "submodule.b.path sub_b\n"
                            "submodule.skip.path sub_skip\n"
                        ),
                        stderr="",
                        returncode=0,
                    )
                return MagicMock(stdout="", stderr="", returncode=0)

            with patch.object(git, "_run_in", side_effect=fake_run_in):
                mismatches = git.submodule_branch_mismatches()

            self.assertEqual(mismatches, [("sub_a", "dev", "main")])

    def test_submodule_branch_mismatches_reports_detached_submodule(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "vendored")
            os.makedirs(sub)
            open(os.path.join(sub, ".git"), "w").close()
            with open(os.path.join(tmp, ".gitmodules"), "w") as fh:
                fh.write("ignored\n")

            git = GIT(tmp)

            def fake_run_in(cwd, *args):
                if args == ("branch", "--show-current"):
                    return MagicMock(
                        stdout="main\n" if cwd == tmp else "",
                        stderr="",
                        returncode=0,
                    )
                if args[:3] == ("config", "--file", ".gitmodules"):
                    return MagicMock(
                        stdout="submodule.v.path vendored\n",
                        stderr="",
                        returncode=0,
                    )
                return MagicMock(stdout="", stderr="", returncode=0)

            with patch.object(git, "_run_in", side_effect=fake_run_in):
                mismatches = git.submodule_branch_mismatches()

            self.assertEqual(mismatches, [("vendored", None, "main")])

    def test_long_description_mirrors_git_status_labels(self):
        self.assertEqual(GitCode.MODIFIED_UNMODIFIED.long_description, "modified (staged)")
        self.assertEqual(GitCode.UNMODIFIED_MODIFIED.long_description, "modified (not staged)")
        self.assertEqual(
            GitCode.MODIFIED_MODIFIED.long_description,
            "modified (staged), modified (not staged)",
        )
        self.assertEqual(GitCode.ADDED_UNMODIFIED.long_description, "new file (staged)")
        self.assertEqual(GitCode.UNMODIFIED_DELETED.long_description, "deleted (not staged)")
        self.assertEqual(GitCode.RENAMED_UNMODIFIED.long_description, "renamed (staged)")
        self.assertEqual(GitCode.UNTRACKED_UNTRACKED.long_description, "untracked")
        self.assertEqual(GitCode.IGNORED_IGNORED.long_description, "ignored")
        self.assertEqual(GitCode.UNMODIFIED_UNMODIFIED.long_description, "unmodified")


class TestStashCommands(unittest.TestCase):
    """git stash push / pop: what the confirmation shows and what runs."""

    def test_stash_command_includes_untracked_files(self):
        """The file list shows untracked files, so a stash that left them
        behind would put away only part of what the user is looking at."""
        self.assertEqual(
            GIT("/tmp/repo").stash_command(),
            ["git", "stash", "push", "--include-untracked"],
        )

    def test_stash_command_limits_itself_to_the_given_filenames(self):
        self.assertEqual(
            GIT("/tmp/repo").stash_command(filenames=["a.py", "dir/b.py"]),
            ["git", "stash", "push", "--include-untracked", "--", "a.py", "dir/b.py"],
        )

    def test_stash_runs_what_stash_command_displays(self):
        git = GIT("/tmp/repo")
        with fake_git_processes() as processes:
            git.stash(filenames=["a.py"])
        self.assertEqual(
            processes.commands,
            [
                ["git", "-c", "color.ui=false", "-C", "/tmp/repo"]
                + git.stash_command(filenames=["a.py"])[1:]
            ],
        )

    def test_stash_entries_lists_the_stash_newest_first(self):
        git = GIT("/tmp/repo")
        stdout = "stash@{0}: WIP on master: abc123 latest\nstash@{1}: WIP on master: def456 older\n"
        with patch.object(git, "_run") as run:
            run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
            entries = git.stash_entries()
        run.assert_called_once_with("stash", "list")
        self.assertEqual(entries[0], "stash@{0}: WIP on master: abc123 latest")
        self.assertEqual(len(entries), 2)

    def test_stash_entries_is_empty_when_nothing_is_stashed(self):
        git = GIT("/tmp/repo")
        with patch.object(git, "_run") as run:
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            self.assertEqual(git.stash_entries(), [])

    def test_stash_pop_runs_what_stash_pop_command_displays(self):
        git = GIT("/tmp/repo")
        self.assertEqual(git.stash_pop_command(), ["git", "stash", "pop"])
        with fake_git_processes() as processes:
            git.stash_pop()
        self.assertEqual(
            processes.commands,
            [["git", "-c", "color.ui=false", "-C", "/tmp/repo", "stash", "pop"]],
        )


class TestShutdown(unittest.TestCase):
    """`GIT.shutdown()`: end the git process in flight, and start no more."""

    def test_shutdown_terminates_every_running_process(self):
        git = GIT("/tmp/repo")
        running = MagicMock()
        git._running.add(running)

        self.assertEqual(git.shutdown(), 1)
        running.terminate.assert_called_once_with()

    def test_shutdown_survives_a_process_that_already_exited(self):
        """The worker's own `finally` may be discarding it at the same moment."""
        git = GIT("/tmp/repo")
        gone = MagicMock()
        gone.terminate.side_effect = OSError("No such process")
        git._running.add(gone)

        self.assertEqual(git.shutdown(), 0)

    def test_after_shutdown_no_command_spawns_a_process(self):
        """Killing the running command is only half of it: a read is several
        commands in a row, so without this the worker walks on to the next."""
        git = GIT("/tmp/repo")
        git.shutdown()

        with fake_git_processes(stdout="M  tracked.py\n") as processes:
            result = git._run("status", "--short")

        self.assertEqual(processes.commands, [])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")


class TestRepositoryChain(unittest.TestCase):
    """`GIT.repository_chain()`: this repo's top level out to the outermost superproject."""

    def test_not_a_submodule_is_a_chain_of_one(self):
        git = GIT("/top/src")
        with fake_git_processes(results=[(0, "/top\n", ""), (0, "", "")]) as processes:
            self.assertEqual(git.repository_chain(), ["/top"])

        self.assertEqual(
            processes.commands[1][-3:], ["/top", "rev-parse", "--show-superproject-working-tree"]
        )

    def test_nested_submodules_walk_out_to_the_top_level(self):
        git = GIT("/top/mid/sub/src")
        results = [
            (0, "/top/mid/sub\n", ""),
            (0, "/top/mid\n", ""),
            (0, "/top\n", ""),
            (0, "", ""),
        ]
        with fake_git_processes(results=results) as processes:
            chain = git.repository_chain()

        self.assertEqual(chain, ["/top/mid/sub", "/top/mid", "/top"])
        # Each step asks from the repository the previous step found.
        self.assertEqual(
            [argv[4] for argv in processes.commands[1:]], ["/top/mid/sub", "/top/mid", "/top"]
        )

    def test_outside_a_repository_is_empty(self):
        git = GIT("/tmp")
        with fake_git_processes(returncode=128, stderr="fatal: not a git repository") as processes:
            self.assertEqual(git.repository_chain(), [])

        self.assertEqual(processes.call_count, 1)

    def test_a_cycle_stops_the_walk(self):
        git = GIT("/a")
        with fake_git_processes(results=[(0, "/a\n", ""), (0, "/b\n", ""), (0, "/a\n", "")]):
            self.assertEqual(git.repository_chain(), ["/a", "/b"])


class TestRemoteCommands(unittest.TestCase):
    """git pull / push: upstream detection and the argv it produces."""

    def test_pull_is_fast_forward_only(self):
        """A merge this app can't drive would leave the repo in a state it
        can't show either, so the pull refuses instead of starting one."""
        self.assertEqual(GIT("/tmp/repo").pull_command(), ["git", "pull", "--ff-only"])

    def test_pull_runs_what_pull_command_displays(self):
        with fake_git_processes() as git:
            GIT("/tmp/repo").pull()
        self.assertEqual(
            git.commands,
            [["git", "-c", "color.ui=false", "-C", "/tmp/repo", "pull", "--ff-only"]],
        )

    def test_upstream_branch_reads_the_tracking_ref(self):
        git = GIT("/tmp/repo")
        with patch.object(git, "_run") as run:
            run.return_value = MagicMock(returncode=0, stdout="origin/master\n", stderr="")
            self.assertEqual(git.upstream_branch(), "origin/master")
        run.assert_called_once_with(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
        )

    def test_upstream_branch_is_none_when_the_branch_has_none(self):
        git = GIT("/tmp/repo")
        with patch.object(git, "_run") as run:
            run.return_value = MagicMock(returncode=128, stdout="", stderr="no upstream\n")
            self.assertIsNone(git.upstream_branch())

    def test_remote_names_are_returned_in_git_order(self):
        git = GIT("/tmp/repo")
        with patch.object(git, "_run") as run:
            run.return_value = MagicMock(returncode=0, stdout="origin\nfork\n", stderr="")
            self.assertEqual(git.remote_names(), ["origin", "fork"])

    def test_push_is_plain_when_the_branch_has_an_upstream(self):
        git = GIT("/tmp/repo")
        with patch.object(git, "upstream_branch", return_value="origin/master"):
            self.assertEqual(git.push_command(), ["git", "push"])

    def test_push_spells_out_set_upstream_for_a_branch_without_one(self):
        """That push publishes the branch on the remote, which is what the
        confirmation has to be able to say."""
        git = GIT("/tmp/repo")
        with (
            patch.object(git, "upstream_branch", return_value=None),
            patch.object(git, "remote_names", return_value=["origin", "fork"]),
            patch.object(git, "branch_name", return_value="feature"),
        ):
            self.assertEqual(
                git.push_command(),
                ["git", "push", "--set-upstream", "origin", "feature"],
            )

    def test_push_falls_back_to_plain_push_with_no_remote_or_branch(self):
        git = GIT("/tmp/repo")
        with (
            patch.object(git, "upstream_branch", return_value=None),
            patch.object(git, "remote_names", return_value=[]),
            patch.object(git, "branch_name", return_value=None),
        ):
            self.assertEqual(git.push_command(), ["git", "push"])

    def test_push_runs_what_push_command_displays(self):
        git = GIT("/tmp/repo")
        with (
            patch.object(git, "upstream_branch", return_value=None),
            patch.object(git, "remote_names", return_value=["origin"]),
            patch.object(git, "branch_name", return_value="feature"),
            patch.object(git, "_run") as run,
        ):
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            git.push()
        run.assert_called_once_with("push", "--set-upstream", "origin", "feature")
