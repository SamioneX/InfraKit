.PHONY: install test lint format typecheck build publish clean

install:
	pip install -e ".[dev]"

test:
	pytest

test-unit:
	pytest tests/unit -m unit -v

test-integration:
	pytest tests/integration -m integration -v

lint:
	ruff check src tests
	mypy src

format:
	ruff format src tests
	ruff check --fix src tests

typecheck:
	mypy src

build:
	pip install build
	python -m build

publish: build
	pip install twine
	twine upload dist/*

clean:
	rm -rf dist/ build/ .eggs/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .coverage htmlcov/ .pytest_cache/ .mypy_cache/ .ruff_cache/

# Run the full CI pipeline locally before pushing
ci: format lint test
	@echo "✅ All checks passed"
