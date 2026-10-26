from __future__ import annotations

import asyncio
import threading
from contextlib import AsyncExitStack
from functools import partial
from typing import Literal
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


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("teardown_phase", ["async", "sync"])
def test_harness_tears_down_infrastructure_before_draining_uploads(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    interrupted: bool,
    teardown_phase: Literal["async", "sync"],
) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    monkeypatch.setenv("LLM_GATEWAY_ANTHROPIC_API_KEY", "test-only-key")
    monkeypatch.delenv("EXPORT_EVAL_RESULTS", raising=False)
    started = asyncio.Event()
    torn_down = asyncio.Event()
    clock_offset = 0.0
    cleanup_thread_id = threading.get_ident()
    server = OfflineServer()
    upload = OfflineEvalUpload(
        host="https://posthog.example.com",
        project_id=123,
        experiment_name="test-experiment",
        experiment={"id": str(UUID(int=1)), "started_at": "2026-01-01T00:00:00Z"},
        results=(),
    )
    publisher = OfflineEvalPublisher(
        OfflineEvalSettings(
            host="https://posthog.example.com", project_id=123, api_key=SecretStr("test"), scorer_versions={}
        ),
        OfflineEvalSuite(key="test/suite", project_id=123, scorer_kinds={}, scorer_versions={}),
    )

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal clock_offset
        started.set()
        await torn_down.wait()
        if not server.requests:
            clock_offset += 45
            resumed = asyncio.Event()
            asyncio.get_running_loop().call_later(0, resumed.set)
            await resumed.wait()
        return server.respond(request)

    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)))

    async def suite(ctx: EvalContext) -> None:
        loop = asyncio.get_running_loop()
        original_time = loop.time
        monkeypatch.setattr(loop, "time", lambda: original_time() + clock_offset)
        assert ctx.offline_delivery is not None
        assert ctx.offline_delivery.submit(publisher, upload)
        await asyncio.wait_for(started.wait(), 5)
        assert not torn_down.is_set()

    monkeypatch.setattr(
        lifecycle,
        "discover_suites",
        lambda _: [
            EvalSuite(
                domain="test",
                module_name="eval_test",
                fn_name="eval_test",
                fn=suite,
                kind=SuiteKind.ONE_SHOT,
                no_send_logs=True,
            )
        ],
    )
    monkeypatch.setattr(lifecycle, "ensure_personhog_binaries", lambda: None)
    harness = lifecycle.SandboxedEvalHarness(parse_args([]))

    def teardown() -> None:
        nonlocal clock_offset
        assert threading.get_ident() == cleanup_thread_id
        clock_offset += 120
        torn_down.set()
        if interrupted:
            raise KeyboardInterrupt

    def bootstrap(required: frozenset[Infra], reporter: lifecycle.ProgressReporter) -> None:
        harness._demo_data = MagicMock()
        if teardown_phase == "sync":
            harness._stack.callback(teardown)

    def async_stack() -> AsyncExitStack:
        stack = AsyncExitStack()
        if teardown_phase == "async":
            stack.callback(teardown)
        return stack

    monkeypatch.setattr(harness, "_bootstrap", bootstrap)
    monkeypatch.setattr(lifecycle, "AsyncExitStack", async_stack)

    assert harness.run() == (130 if interrupted else 0)
    assert torn_down.is_set()
    output = capsys.readouterr().out
    if interrupted:
        assert server.requests == []
        assert output.count("upload failed: upload interrupted") == 1
        assert "Results were not saved for retry." in output
    else:
        assert server.requests[-1].url.path.endswith("/complete/")
        assert "POSTHOG OFFLINE  test-experiment  https://posthog.example.com/project/123/" in output
        assert "upload failed:" not in output
