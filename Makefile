.PHONY: fmt lint typecheck test check

fmt:
	ruff format company_briefer tests
	ruff check --fix company_briefer tests

lint:
	ruff check company_briefer tests
	ruff format --check company_briefer tests

typecheck:
	mypy company_briefer

test:
	pytest --cov=company_briefer --cov-report=term-missing --cov-fail-under=90

check: lint typecheck test
