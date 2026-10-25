-include .env
export

PYTHON ?= python3

.PHONY: install lint typecheck test-unit test-integration test check db-up db-down

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy

test-unit:
	pytest tests/unit

test-integration:
	@test -n "$$SCHEMADIFF_PG_URL" || (echo "SCHEMADIFF_PG_URL is not set (copy .env.example to .env)" >&2; exit 2)
	@test -n "$$SCHEMADIFF_MYSQL_URL" || (echo "SCHEMADIFF_MYSQL_URL is not set (copy .env.example to .env)" >&2; exit 2)
	SCHEMADIFF_REQUIRE_DB=1 pytest tests/integration

# Unit and integration tests in one run so branch coverage covers both.
test:
	@test -n "$$SCHEMADIFF_PG_URL" || (echo "SCHEMADIFF_PG_URL is not set (copy .env.example to .env)" >&2; exit 2)
	@test -n "$$SCHEMADIFF_MYSQL_URL" || (echo "SCHEMADIFF_MYSQL_URL is not set (copy .env.example to .env)" >&2; exit 2)
	SCHEMADIFF_REQUIRE_DB=1 pytest --cov --cov-report=term-missing

check: lint typecheck test

db-up:
	@test -f .env || cp .env.example .env
	docker compose --env-file .env up -d --wait

db-down:
	docker compose --env-file .env down -v
