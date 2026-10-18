# Contributing to Hic Pic Nunc

Thanks for contributing to Hic Pic Nunc!

This guide covers the local development setup, project structure, checks, and workflow for contributing changes.

## Setup

### Prerequisites

You will need:

* Python 3.11
* [`uv`](https://docs.astral.sh/uv/)
* [`just`](https://github.com/casey/just)

Clone the repository and enter the project directory:

```bash
git clone https://github.com/NicoPietrusco/HicPicNunc.git
cd HicPicNunc
```

Create the development environment and install dependencies:

```bash
just setup
```

This creates a Python 3.11 virtual environment and installs the development dependencies.

Then install the git hooks once:

```bash
just hooks
```

From then on, every commit runs the checks below on the files it changes: formatting, final newlines, YAML and TOML syntax, ruff, ty, the `uv.lock` check and the workflow audit. Hooks that fix files themselves, such as the formatter, stop the commit so you can review the changes and stage them again.

### Google Photos OAuth setup

When running Hic Pic Nunc from source, you need your own Google OAuth Desktop client. The release OAuth client is not shared for development.

Follow the setup instructions in [`docs/google-oauth-setup.md`](docs/google-oauth-setup.md) to create and configure your Desktop OAuth client.

After setup, start the local web application with:

```bash
just web
```

You can also verify the local setup with:

```bash
just verify
```

## Project layout

The main source code is organized as follows:

```text
src/hicpicnunc/
├── core/
├── google_photos/
└── web/
```

* `src/hicpicnunc/core/` — EXIF processing, metadata field selection, and export jobs.
* `src/hicpicnunc/google_photos/` — Google OAuth and Google Photos Picker API client.
* `src/hicpicnunc/web/` — Flask app factory, routes, templates, and static files.
* `tests/` — Mirrors `src/hicpicnunc/`; tests use the `*_test.py` naming convention.
* `packaging/` — PyInstaller configuration for desktop releases.

## Checks

Before opening a pull request, run the project's quality checks:

```bash
just check
just test
```

`just check` runs every hook on all files, exactly as the CI `checks` job does. The hooks are defined in [`.pre-commit-config.yaml`](.pre-commit-config.yaml) and run with [prek](https://github.com/j178/prek). Tools such as ruff, ty and zizmor come from `uv.lock`, so the versions are the same locally and in CI. `just lint`, `just typecheck` and `just lint-workflows` still run single tools.

CI also measures test coverage and fails if it drops below the `fail_under` threshold in `pyproject.toml`. Run `just coverage` to see the same report locally, with an HTML version in `htmlcov/`. If your change adds code, add tests for it rather than lowering the threshold.

If you change anything under `.github/`, pin new actions to a full commit SHA with the version as a comment (`uses: owner/action@<sha> # v1.2.3`), and set `persist-credentials: false` on `actions/checkout`.

You can format the source code with:

```bash
just format
```

To build the desktop package locally:

```bash
just package
```

CI runs on Ubuntu, Windows, and macOS, so changes should work across all supported platforms.

## Development workflow

* Create your branch from `main`.
* Keep commits small and use clear commit messages.
* Do not push directly to `main`.
* Open a pull request when your changes are ready for review.
* Pull requests are squash-merged: each one becomes a single commit on `main`, with the PR title as its message and the PR description as its body.

Before submitting a pull request, make sure the relevant checks pass locally.

### Pull request titles

Because the PR title becomes the commit message on `main`, it must follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, where the scope is optional. The `pr-title` check enforces it and runs again when you edit the title, so a failing title can be fixed without pushing new commits.

Allowed types: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`, `ci`, `build`, `perf`, `style` and `revert`.

| Title | Result |
| --- | --- |
| `feat(auth): add sign out` | passes |
| `fix: keep capture dates for HEIC photos` | passes |
| `docs: explain the OAuth setup` | passes |
| `Feat/signout switch account` | fails: no `type:` prefix |
| `feature: add sign out` | fails: unknown type |

Commits inside your branch don't need to follow the format, since they are squashed away.

## Privacy

Hic Pic Nunc handles Google Photos data locally, so privacy-related changes require special care.

If a change:

* adds a new network call, or
* adds a new Google API scope,

update [`site/privacy.html`](site/privacy.html) in the same change so that the privacy policy accurately describes the application's behavior.

Please also mention the relevant privacy-policy update in your pull request.

## Pull requests and issues

Use the provided GitHub issue and pull request templates when opening issues or pull requests. Include enough detail for another contributor to reproduce, review, or test the change.
