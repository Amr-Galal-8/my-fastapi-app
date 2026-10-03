.PHONY: install run test lint format migrate admin up down logs

install:
	uv sync --all-groups

run:
	uv run uvicorn app.main:app --reload

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

migrate:
	uv run alembic upgrade head

admin:
	uv run python -m app.bootstrap_admin

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api
