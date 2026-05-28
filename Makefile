VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn

PORT ?= 8080

.PHONY: help test dev install

help:
	@echo "Targets:"
	@echo "  make test       Run the full pytest suite"
	@echo "  make dev        Run uvicorn with --reload on port $(PORT) (override with PORT=...)"
	@echo "  make install    Sync the editable install with pyproject.toml"

test:
	$(PYTEST) tests/ -v

dev:
	$(UVICORN) app.main:app --port $(PORT) --reload

install:
	$(PIP) install -e .
