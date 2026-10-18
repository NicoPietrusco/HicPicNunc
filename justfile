# Hic Pic Nunc — https://github.com/casey/just
# Install: brew install just  (or see https://github.com/casey/just)

set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Release asset naming: arm64 on Apple Silicon, x64 on Intel
mac_arch := if arch() == "aarch64" { "arm64" } else { "x64" }

# List recipes (run when you type: just)
default:
    @just --list

# Launch the Flask web app
[group('Run')]
run: web

# Confirm client_secrets.json is present and the Flask app loads
[group('Setup')]
verify:
    uv run python scripts/verify_setup.py

[group('Run')]
web:
    @echo "Launching Flask app..."
    uv run hicpicnunc

[group('Setup')]
install:
    @echo "Installing dependencies..."
    uv sync --group dev
    @echo "Done."

# Build a local desktop bundle for the current operating system
[group('Packaging')]
package:
    uv run pyinstaller --noconfirm --clean packaging/pyinstaller.spec

# Create a distributable macOS disk image after `just package`
[group('Packaging')]
package-macos: package
    hdiutil create -volname "Hic Pic Nunc" -srcfolder "dist/Hic Pic Nunc.app" -ov -format UDZO "dist/HicPicNunc-macOS-{{mac_arch}}.dmg"

[group('Setup')]
setup:
    @echo "Creating venv (Python 3.11)..."
    uv venv --python python3.11 .venv
    uv sync --group dev
    @echo "Done."

# Install the git hooks, so every commit runs the `just check` hooks on its staged files
[group('Setup')]
hooks:
    uv run --frozen prek install

# Run every hook on all files, as CI does: lint, format, types, lock file, workflow audit
[group('Quality')]
check:
    uv run --frozen prek run --all-files

[group('Quality')]
lint:
    uv run ruff check src/ tests/

# Audit GitHub Actions workflows and Dependabot config for security issues
[group('Quality')]
lint-workflows:
    uv run zizmor .github

[group('Quality')]
typecheck:
    uv run ty check src/

[group('Quality')]
test:
    uv run pytest

# Run the tests with coverage, as CI does, and write an HTML report to htmlcov/
[group('Quality')]
coverage:
    uv run pytest --cov --cov-report=term-missing --cov-report=html

[group('Quality')]
format:
    uv run ruff format src/ tests/

[group('Maintenance')]
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type f -name ".DS_Store" -delete 2>/dev/null || true
    @echo "Cache cleaned."

[group('Maintenance')]
clean-all: clean
    rm -rf data/outputs/* data/uploads/* 2>/dev/null || true
    @echo "Outputs cleaned."
