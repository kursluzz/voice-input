# Contributing

Thanks for your interest! Bug reports, ideas and pull requests are welcome.

## Reporting bugs

Use the bug report form and include the output of `voice-input --version` and
`voice-input doctor`, how you installed the program, your desktop and session (for example GNOME
on Wayland), the exact steps and the full error. The log never contains dictated text, but check
it before posting.

## Development setup

You need Linux, [uv](https://docs.astral.sh/uv/) and PortAudio (`sudo apt install libportaudio2`).

```bash
git clone https://github.com/kursluzz/voice-input.git
cd voice-input
uv sync                      # the package and the development tools
uv run pytest                # fast; no microphone, model, network or display needed
uv run ruff check . && uv run ruff format --check .
uv run mypy                  # strict
```

Run the application from the clone with `uv run voice-input …`, for example
`uv run voice-input doctor` or `uv run voice-input --log-level DEBUG daemon`. Stop an installed
daemon first (`voice-input shutdown`): only one can run.

### Optional test suites

| Suite | How to run | Why it is optional |
|---|---|---|
| X11 selections | `VOICE_INPUT_TEST_X11=1 uv run pytest tests/test_xselection.py` (or under `xvfb-run -a`) | Replaces the clipboard of the display it runs on. CI runs it under Xvfb. |
| Real recognition | `VOICE_INPUT_TEST_SAMPLES=/path/to/samples uv run pytest -m model` | Downloads a model and needs recordings: `en.wav`, `ru.wav`, `he.wav` and `texts.json` with the expected texts. Audio is not kept in the repository. |

## Guidelines

- **Tests first.** Behaviour changes come with tests. The controller, the insertion backends and
  the desktop integration all take their collaborators as arguments, so tests use fakes instead
  of microphones, models, `gsettings` or `/dev/uinput`.
- Keep pull requests focused: one change per pull request.
- Update `CHANGELOG.md` under `## [Unreleased]` for user-visible changes, and the README or
  `docs/` when behaviour or installation changes.
- Do not commit recordings, models, logs or personal configuration.
- Discuss changes to the daemon protocol ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) in an
  issue first; old clients must keep working.
- Never log or print dictated text outside the commands whose purpose is to print it.
- CI must pass: tests on Python 3.12, 3.13 and 3.14, lint and types, and the package build.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`,
`fix:`, `docs:`, `test:`, `build:`, `ci:`, `refactor:`) and reference the issue (`Refs #12`,
`Closes #12`).

## Project tracking

Work is planned in [milestones](https://github.com/kursluzz/voice-input/milestones); each piece of
work is an [issue](https://github.com/kursluzz/voice-input/issues). Ideas for later live in the
"Backlog" milestone.

## Releases

Contributors do not change version numbers. A maintainer releases like this:

1. On a clean `main`, run `uv run bump-my-version bump patch` (or `minor`/`major`). It updates
   `pyproject.toml`, the README version line and `uv.lock`, moves `[Unreleased]` in
   `CHANGELOG.md` to a dated section, commits and creates the tag `v<version>`.
2. `git push origin main --follow-tags`. The tag starts the release workflow: it runs CI on the
   tagged commit, checks that the tag matches the version, builds the wheel and sdist, and creates
   the GitHub Release with both attached and the changelog section as notes.

The first release, 0.1.0, already has its version: rename `## [Unreleased]` to
`## [0.1.0] - <date>`, add a new empty `## [Unreleased]` above it, commit, and tag with
`git tag -a v0.1.0 -m "Release 0.1.0"`.

PyPI is not used yet; users install from GitHub.

## Licence

By contributing you agree that your contribution is licensed under the MIT licence of the project.
