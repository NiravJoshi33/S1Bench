.PHONY: check test fix

# Everything a reviewer would flag by tool: lint, formatting, types. Run before saying "done".
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright

test:
	uv run pytest

# Apply the fixes the tools can make on their own.
fix:
	uv run ruff check --fix .
	uv run ruff format .
