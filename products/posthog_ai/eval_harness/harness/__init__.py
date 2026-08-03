"""Standalone runner for the sandboxed agent evals.

Replaces pytest as the driver: boots the shared session infrastructure once
(test DB, Django live server, LLM gateway, MCP server, Temporal), then runs
every selected eval suite concurrently on one event loop with a single global
sandbox semaphore bounding total load. Braintrust stays as the eval engine.

    python -m products.posthog_ai.eval_harness.harness --help
"""
