VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn

PORT ?= 8080

.PHONY: help test test-sdk test-sdk-forked dev install

help:
	@echo "Targets:"
	@echo "  make test       Run the full pytest suite"
	@echo "  make test-sdk   Run the SDK defect-hunting suite"
	@echo "  make test-sdk-forked  Same, process-isolated (currently hangs — SDK-043)"
	@echo "  make dev        Run uvicorn with --reload on port $(PORT) (override with PORT=...)"
	@echo "  make install    Sync the editable install with pyproject.toml"

test:
	$(PYTEST) tests/ --ignore=tests/sdk -v

test-sdk:  ## Run the SDK defect-hunting suite
	# No --forked. It was required because SDK-003 corrupted process-wide native
	# state, making sequential single-process runs unreliable. 1.0.9 fixed
	# SDK-003 (verified in PR #28), and forking now HANGS INDEFINITELY on the
	# markdown -> PDF path (SDK-043) — two tests convert markdown, and the run
	# blocks forever with no output. Sequential is both green and faster: 82
	# tests in ~32s.
	#
	# To re-check fork behaviour after an SDK bump: make test-sdk-forked
	$(PYTEST) tests/sdk/ -v -rxX

test-sdk-forked:  ## Run the SDK defect suite process-isolated (currently hangs — SDK-043)
	$(PYTEST) tests/sdk/ --forked -v -rxX

dev:
	$(UVICORN) app.main:app --port $(PORT) --reload

install:
	$(PIP) install -e .
