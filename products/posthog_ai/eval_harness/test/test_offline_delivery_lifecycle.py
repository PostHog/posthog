from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from uuid import UUID

import pytest
from unittest.mock import MagicMock

import httpx
from pydantic import SecretStr

from products.posthog_ai.eval_harness.harness import lifecycle
from products.posthog_ai.eval_harness.harness.cli import parse_args
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.discovery import EvalSuite
from products.posthog_ai.eval_harness.harness.requirements import Infra, SuiteKind
from products.posthog_ai.eval_harness.offline_results import (
    OfflineEvalPublisher,
    OfflineEvalSettings,
    OfflineEvalSuite,
    OfflineEvalUpload,
)
from products.posthog_ai.eval_harness.test.offline_api import OfflineServer


def test_harness_tears_down_infrastructure_before_draining_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "test-only-key")
    monkeypatch.setenv("LLM_GATEWAY_ANTHROPIC_API_KEY", "test-only-key")
    monkeypatch.delenv("EXPORT_EVAL_RESULTS", raising=False)
    started = asyncio.Event()
    torn_down = asyncio.Event()
    server = OfflineServer()
    path = tmp_path / "upload.json"
    OfflineEvalUpload(
        host="https://posthog.example.com",
        project_id=123,
        experiment_name="test-experiment",
        experiment={"id": str(UUID(int=1)), "started_at": "2026-01-01T00:00:00Z"},
        items=(),
        results=(),
    ).save(path)
    publisher = OfflineEvalPublisher(
        OfflineEvalSettings(
            host="https://posthog.example.com", project_id=123, api_key=SecretStr("test"), scorer_versions={}
        ),
        OfflineEvalSuite(key="test/suite", scorer_kinds={}),
    )

    async def respond(request: httpx.Request) -> httpx.Response:
        started.set()
        await torn_down.wait()
        return server.respond(request)

    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)))

    async def suite(ctx: EvalContext) -> None:
        assert ctx.offline_delivery is not None
        assert ctx.offline_delivery.submit(publisher, path, "test-experiment")
        await asyncio.wait_for(started.wait(), 5)
        assert not torn_down.is_set()

    monkeypatch.setattr(
        lifecycle,
        "discover_suites",
        lambda _: [
            EvalSuite(domain="test", module_name="eval_test", fn_name="eval_test", fn=suite, kind=SuiteKind.ONE_SHOT)
        ],
    )
    monkeypatch.setattr(lifecycle, "ensure_personhog_binaries", lambda: None)
    harness = lifecycle.SandboxedEvalHarness(parse_args([]))

    def bootstrap(required: frozenset[Infra]) -> None:
        harness._demo_data = MagicMock()
        harness._stack.callback(torn_down.set)

    monkeypatch.setattr(harness, "_bootstrap", bootstrap)

    assert harness.run() == 0
    assert torn_down.is_set()
    assert server.requests[-1].url.path.endswith("/complete/")
    assert "POSTHOG OFFLINE  test-experiment  https://posthog.example.com/project/123/" in capsys.readouterr().out
    assert OfflineEvalUpload.load(path).experiment["id"] == str(UUID(int=1))
