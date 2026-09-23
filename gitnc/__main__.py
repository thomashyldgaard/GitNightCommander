"""Entry point for `python -m gitnc` and the `gitnc` CLI script."""

import sys

from gitnc.app import GitNightCommanderApp


def main() -> None:
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "."
    app = GitNightCommanderApp(repo_path=repo_path)
    app.run()


if __name__ == "__main__":
    main()
