# List available recipes
default:
    @just --list

# Create .venv, install dev+docs dependencies, and install git hooks
setup:
    python -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e '.[dev,docs]'
    just install-hooks
    @echo "Setup complete. Activate your environment with: source .venv/bin/activate"

# Install git hooks from hooks/
install-hooks:
    cp hooks/pre-commit .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit

# Run ruff linter on source code
lint:
    ruff check src/wayback

# Format source code with ruff
format:
    ruff format src/wayback

# Check formatting without modifying files (used in CI)
format-check:
    ruff format --check src/wayback

# Run mypy type checker
typecheck:
    mypy

# Run tests with verbose output
test:
    pytest -v src/wayback/tests

# Build HTML documentation
docs:
    sphinx-build -M html docs/source docs/build "-W"

# Remove build artifacts, caches, and compiled files
clean:
    find . -type d -name __pycache__ -exec rm -rf {} +
    find . -type f -name '*.pyc' -delete
    find . -type d -name '*.egg-info' -exec rm -rf {} +
    rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/
