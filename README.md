# GitNightCommander

Yet another git terminal tool. GitNightCommander is a TUI whose interface is
inspired by [Midnight Commander](https://midnight-commander.org/) — the
two-pane layout, the F-key row, the dropdown menus — but it doesn't aim to be
a Midnight Commander replacement: it's only about git. It's built with
[Textual](https://github.com/Textualize/textual).

Main features:

- **Easy handling of commits in projects that use git submodules** — staging
  and committing walk the submodules for you, and pull/push warn when a
  submodule sits on a branch of its own.
- **`Ctrl+O` switches to the command line** — drops the app to a `$SHELL` in
  the same terminal; press `Ctrl+O` again to switch back with the TUI right
  where you left it. Started from Midnight Commander's command line, mc keeps
  `Ctrl+O` for its own panels, so the app warns at startup and asks whether
  to continue (`C` / `Enter`) or exit (`E` / `Esc`).
- **Every git operation shows the exact commands about to run** — the
  confirmation dialog is the last thing between the keypress and the wire, so
  there is never any guessing what a shortcut will do.
- **Easy diff view for file changes** — press `Enter` on any file to see its
  diff, either inline beside the file list or full-screen; `F3` toggles
  between the two modes.
- **Quick filter for untracked folders** — `f` collapses a folder whose files
  have never been added to git into one row instead of listing every file
  below it; the status line under the file list shows which filter is active.
- **Optional commit-message drafting** — Settings hooks any command line you
  name (e.g. `claude -p`) into the commit dialog's `F4` button, with support
  for picking between several numbered suggestions.
- **Non-blocking UI** — git reads run on worker threads, so `git log` and
  `git status` on a large repo never freeze the interface, and `F10` quits
  even while a read is in flight.
- **Stash, pull and push as first-class actions** — pull and push run in the
  background so the interface stays live, and stash includes untracked files
  by default because they're in the list you're looking at.

GitNightCommander has mainly been built with the help of
[Claude](https://claude.ai/).

Released under the [GNU General Public License v3](LICENSE).

## Requirements

- Python 3.12+
- Git

Additional tools depend on what you're doing: [Hatch](https://hatch.pypa.io/)
for the build/test workflow below, or [pipx](https://pipx.pypa.io/) for the
recommended installation.

Runtime dependencies (`textual>=0.80.0`, `pyyaml>=6.0`) and dev tools (`ruff`,
`pyright`) are pulled in by Hatch and by the installation methods below.

## Build

### Dev Container (recommended)

The repo ships a dev container under `.devcontainer/` that installs everything
you need — Python, Git, Hatch, and a `.venv` with the project in editable mode
plus the `dev` extra (ruff, pyright). Open the folder in VS Code and choose
**Reopen in Container**; the interpreter (`${workspaceFolder}/.venv/bin/python`)
is preconfigured, and every `hatch` command below works without further setup.

The container also has the [Claude Code](https://claude.com/claude-code) CLI
installed: the `claude` command is on the `PATH` (installed globally with npm
under `~/.npm-global`, on the Node.js LTS the image ships for it). It
doesn't have its own configuration. `devcontainer.json` bind-mounts the host's
Claude files into the container user's home:

| Host                | Container                   |
|---------------------|-----------------------------|
| `~/.claude/`        | `/home/vscode/.claude/`     |
| `~/.claude.json`    | `/home/vscode/.claude.json` |

so `claude` in the container uses the host's login, settings, memory and
session history, and anything it changes there is written back to the host.
Both paths have to exist on the host before the container is built, or the
mount fails. If you have never run Claude Code on the host, create them first
(`mkdir -p ~/.claude && echo '{}' > ~/.claude.json`). This is also what makes
`claude -p` work as the commit-drafting command (see
[Commit messages](#commit-messages)) from inside the container.

If you'd rather not use the container, install
[Hatch](https://hatch.pypa.io/latest/install/) yourself — `pipx install hatch`
is the usual way. Hatch creates its own virtualenv with the `dev` extra on
first use, so no manual venv activation is needed for the commands below.

### Building the package

```sh
hatch build              # sdist + wheel into dist/
```

The artifacts land in `dist/` as `gitnc-<version>-py3-none-any.whl` and
`gitnc-<version>.tar.gz`, ready to install (see [Installation](#installation))
or upload to PyPI.

### Running tests

```sh
hatch run test                                  # all tests
hatch run test tests.test_app                   # one module
hatch run test tests.test_app.TestGitNightCommanderApp.test_quit_binding_uses_f10  # one test
```

Unittest args pass straight through, so `-v`, `-k`, etc. work as usual.

### Ad-hoc execution

Run the app straight from the source tree, without installing it:

```sh
hatch run start                # current directory
hatch run start /path/to/repo  # another repo
```

### Linting and formatting

```sh
hatch run lint           # ruff check + ruff format --check + pyright
hatch run fmt            # ruff check --fix + ruff format
```

## Installation

The `gitnc` package declares a console script, so once it's installed the
`gitnc` command is on your `PATH` — no `python -m …` needed.

### From PyPI (recommended)

[pipx](https://pipx.pypa.io/) installs the package into its own isolated
virtualenv and links `gitnc` into a directory on your `PATH`:

```sh
pipx install gitnc
gitnc --help
```

Plain `pip` works too if you'd rather manage the environment yourself:

```sh
pip install --user gitnc
```

For `pip install --user` to expose the command, `~/.local/bin` (Linux/macOS)
must be on your `PATH`.

### From a built artifact

After `hatch build`, install one of the files it wrote into `dist/`:

```sh
pipx install dist/gitnc-0.1.1-py3-none-any.whl
# or
pip install --user dist/gitnc-0.1.1.tar.gz
```

Substitute the version in the filename for whatever `hatch build` produced.

### From a source checkout

```sh
pipx install .           # from the project root
```

For development work — editable install into a local venv, with the `dev`
extra — use pip instead:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Usage

Browse the git log for the current repository:

```sh
gitnc
```

Browse a different repository by passing its path:

```sh
gitnc /path/to/repo
```

You can also run it as a module (equivalent to the `gitnc` script), or via
Hatch without installing:

```sh
python -m gitnc [path]
hatch run start [path]
```

## VS Code (without the dev container)

If Pylance reports `Import "rich.text" could not be resolved` (or similar for
`textual`), VS Code is using an interpreter that doesn't have the project's
dependencies. Point it at a virtualenv that does — e.g. one you created with
`pip install -e '.[dev]'`:

1. `Ctrl+Shift+P` → **Python: Select Interpreter** → pick `./.venv/bin/python`.
2. Reload the window (`Ctrl+Shift+P` → **Developer: Reload Window**).

To pin this per-workspace, create `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"
}
```

## Keybindings

| Key | Action  |
|-----|---------|
| `F1` | Keyboard shortcut reference |
| `F5` | Refresh |
| `f` | Toggle the file-list filter: all files, or untracked folders collapsed to one row |
| `F7` | Restore selected file(s) to their `HEAD` state (asks first) |
| `F8` / `Del` | Delete selected file(s) (asks first) |
| `s` / `u` | Stage / unstage selected file(s) (asks first) |
| `c` / `F2` | Commit selected file(s) |
| `p` / `Shift+P` | Pull / push (asks first) |
| `z` / `Shift+Z` | Stash / stash pop (asks first) |
| `Ctrl+O` | Toggle the pre-launch terminal screen and open your `$SHELL` |
| `F10` / `q` | Quit — `q` for terminals that keep F10 for themselves (VS Code's gives it to the debugger) |

Function keys are the file-manager row every TUI in this lineage uses; letters
are the git verbs, and shift is the other half of a pair. The four repo
commands are in the **Repo** menu as well, with their keys in the hint column.

## Stash, pull and push

All four ask before they run, showing the exact command:

- `z` stashes. With files selected it stashes those (`git stash push
  --include-untracked -- <files>`); with nothing selected the whole worktree
  goes. Untracked files are included — they are in the list you are looking at
  — and gitignored ones are not. Files inside a submodule can't go in a
  path-limited stash, and the dialog says how many were left alone.
- `Shift+Z` pops. The question names the entry it would reapply, so two stashes
  can be told apart, and it says how many are waiting.
- `p` pulls with `--ff-only`. A pull that has to merge would leave the repo in
  a state this app can neither show nor finish, so it refuses instead — the
  message says what diverged, and `Ctrl+O` is a shell away.
- `Shift+P` pushes. A branch with no upstream is pushed with `--set-upstream`,
  and the confirmation says that it publishes the branch rather than updating
  it.

Pull and push run in the background, so the interface stays live while the
network does not; the result is reported when git comes back, and both views
reload.

## Commit messages

`c` opens the commit dialog for the selected file(s) — after a `Stage N file(s)
for commit?` prompt when any of them still has unstaged changes. The dialog
fills the whole screen, and its text box takes every row the rest of the dialog
doesn't need; a longer message scrolls inside it, with the arrow keys,
`PgUp`/`PgDn` or the mouse wheel. `F2` hands the message on to a `Commit N file(s)?`
confirmation listing every command the commit will run. `Y` runs them; `N` puts
you back in the dialog with the message you just wrote.

Options -> Settings configures the things it uses:

- **Use branch name as prefix in commit messages** — prefills the message with
  `<branch>: `, and puts that prefix in front of a drafted message that does not
  already start with the branch name.
- **Commit message editor** — where the message is written:
  - **Built-in editor** (the default) is the commit dialog described above.
  - **$EDITOR** runs the editor named by the `EDITOR` environment variable;
    the row shows what it is currently set to.
  - **Other editor** runs the command line typed under it, e.g. `code --wait`
    or `nano`. Typing a command selects this option.

  An external editor opens the message in a temporary `COMMIT_EDITMSG` file,
  the name git itself uses, so editors with a git-commit mode switch into it.
  The app is suspended while the editor runs, as it is for `Ctrl+O`. Under the
  message the file lists the files going into the commit below git's scissors
  line (`# ---- >8 ----`); everything from that line down is ignored, and lines
  above it are kept even when they start with `#`. Saving and quitting goes on
  to the `Commit N file(s)?` confirmation, and `N` there reopens the editor on
  the same message. An empty message, one that is only the branch prefix, or
  an editor that exits with an error status (vim's `:cq`) cancels the commit.
  A GUI editor has to be told to wait for the file to be closed (`code
  --wait`, `subl -w`), or it returns at once with the message unchanged.

  If the external editor cannot be used — `EDITOR` is not set, the command is
  empty or cannot be started, or the terminal cannot be suspended — the app
  says so and opens the built-in dialog instead. The **Draft (F4)** button
  below belongs to that dialog, so it is not available with an external
  editor.
- **Tool for drafting commit messages** — a command line and a prompt template,
  under the dialog's **Experimental** heading along with the numbered-list
  setting below. The template is typed into a framed field of its own, several
  lines tall and word-wrapped: it is a paragraph rather than a word, so it is
  shown whole instead of scrolling through a single line. The field grows with
  what you type and scrolls once it is eight lines tall.

  Tab into the field and the arrow keys are the caret's: `←→` move it a
  character, `↑↓` a wrapped line, and what you type goes in where it is. They
  stay the caret's until you leave the field — `Tab` for the next setting,
  `Enter` to save — so `↑` on the first line and `↓` on the last go to the
  start and the end of the template rather than to the row above or below.

  The dialog's **Draft (F4)** button runs

  ```sh
  <command> "<prompt template>
  <file being committed>
  ..."
  ```

  and loads what the command prints on stdout into the message, where it stays
  editable. For example, a command of `claude -p` with the default prompt asks
  Claude Code to write the message for the files in the commit. The command line
  is split the way a shell splits it; the prompt and file list are passed as a
  single argument.

  The command runs on the previous screen — the terminal `Ctrl+O` shows — with
  the TUI suspended for the length of the run, so everything it prints (stdout
  and stderr both) appears at full screen height as it arrives, the way it
  would if you had typed the command yourself. `Ctrl+C` there stops the tool
  and returns to the dialog. What it printed stays in the terminal's
  scrollback, so `Ctrl+O` from the main screen still shows the run long after
  the commit.

  The same output is captured: the message is what the command printed on
  stdout. It is not repeated inside the dialog — you have just watched the run,
  and the dialog is for the message. In a terminal that cannot be suspended the
  command runs in the background instead, and then its output does show in a
  log under the dialog's buttons, since there is nowhere else to see it.
- **Parse suggestions from numbered list** — for a prompt that asks the tool for
  several candidate messages, e.g. `Suggest three commit messages, numbered, for
  these files:`. The output is read back as a numbered list:

  ```
  Here are three options:
  1. feat: add the widget
  2. fix: stop the widget crashing
  3. chore: tidy the widget
  ```

  and the items are offered in a picker — `↑↓` moves, `Enter` or the row's digit
  picks, `Esc` cancels. The pick lands in the message where it stays editable,
  so `F2` still commits whatever you leave there.

  Anything before the first number is dropped, and an item keeps the lines
  indented under it, so a suggestion with a body survives — indented, because
  everything a tool writes about the list afterwards ("My pick: #2, because…")
  starts back in the first column, and that is where the item it follows ends.
  Output with no numbered list in it goes into the message whole, as it does
  with the setting off.

They live in the app's `settings.json`: the editor as `commit_editor`
(`builtin`, `environment` or `command`) and `commit_editor_command`, the
drafting tool as `commit_draft_command`, `commit_draft_prompt` and
`commit_draft_parse_suggestions`.

## Interface

The UI is split into two panes:

- **Left** — scrollable list of the last 200 commits, showing short hash, date, and subject.
- **Right** — commit metadata (hash, author, date) and a `git show --stat` summary for the selected commit.

## License

GitNightCommander is free software, licensed under the [GNU General Public
License, version 3](LICENSE) or (at your option) any later version. See the
[`LICENSE`](LICENSE) file for the full text.
