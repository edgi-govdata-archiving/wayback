.PHONY: lint format typecheck test docs setup install-hooks clean help

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Create .venv, install dev+docs dependencies, and install git hooks
	python -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e '.[dev,docs]'
	$(MAKE) install-hooks
	@echo "Setup complete. Activate your environment with: source .venv/bin/activate"

install-hooks: ## Install git hooks from hooks/
	cp hooks/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit

lint: ## Run ruff linter on source code
	ruff check src/wayback

format: ## Format source code with ruff
	ruff format src/wayback

typecheck: ## Run mypy type checker
	mypy

test: ## Run tests with verbose output
	pytest -v src/wayback/tests

docs: ## Build HTML documentation
	make -C docs html

clean: ## Remove build artifacts, caches, and compiled files
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	find . -type d -name '*.egg-info' -exec rm -rf {} +
	rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/
