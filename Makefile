.PHONY: run test lint typecheck format

# make run CONFIG=path/to/config.toml
run:
	uv run pitwall $(if $(CONFIG),-c "$(CONFIG)")

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
