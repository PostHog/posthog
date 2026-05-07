.PHONY: help new-user returning-user check-loading test test-integration mcp-server clean

PYTHON ?= uv run python

help:
	@echo "traffic-sim — verify PostHog instrumentation by driving a real browser"
	@echo ""
	@echo "Targets:"
	@echo "  make new-user URL=...        Run new-user scenario (override VISITS, INTERVAL)"
	@echo "  make returning-user URL=...  Run returning-user scenario (override PAGE_VIEWS, INTERVAL)"
	@echo "  make check-loading URL=...   Inspect how PostHog loads on URL(s)"
	@echo "  make test                    Run unit tests (no network)"
	@echo "  make test-integration        Run integration test (spawns local fixture page)"
	@echo "  make mcp-server              Start the MCP server in stdio mode"
	@echo "  make clean                   Remove results/ directory"
	@echo ""
	@echo "Variables:"
	@echo "  URL=https://example.com   Required for the three scenarios"
	@echo "  VISITS=10                 Override new-user visit count"
	@echo "  PAGE_VIEWS=5              Override returning-user page-view count"
	@echo "  INTERVAL=60               Override seconds between visits"
	@echo "  POSTHOG_HOST=https://...  Override PostHog ingestion host"

VISITS ?= 3
PAGE_VIEWS ?= 3
INTERVAL ?= 5
POSTHOG_HOST ?= https://us.i.posthog.com

new-user:
	@if [ -z "$(URL)" ]; then echo "URL=... is required"; exit 1; fi
	$(PYTHON) cli.py new-user --url "$(URL)" --visits $(VISITS) --interval $(INTERVAL) --posthog-host "$(POSTHOG_HOST)"

returning-user:
	@if [ -z "$(URL)" ]; then echo "URL=... is required"; exit 1; fi
	$(PYTHON) cli.py returning-user --url "$(URL)" --page-views $(PAGE_VIEWS) --interval $(INTERVAL) --posthog-host "$(POSTHOG_HOST)"

check-loading:
	@if [ -z "$(URL)" ]; then echo "URL=... is required (or pass --urls-file ...)"; exit 1; fi
	$(PYTHON) cli.py check-loading --url "$(URL)" --posthog-host "$(POSTHOG_HOST)"

test:
	$(PYTHON) -m pytest tests/test_cli.py -q

test-integration:
	$(PYTHON) -m pytest tests/test_integration.py -q

mcp-server:
	$(PYTHON) mcp_server.py

clean:
	rm -rf results/
