.PHONY: run test lint format

run:
	uv run pitwall

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

format:
	uv run ruff check --fix .
	uv run ruff format .
