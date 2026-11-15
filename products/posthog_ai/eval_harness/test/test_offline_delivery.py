from __future__ import annotations

import json
import asyncio
import threading
from collections.abc import Callable, Coroutine
from dataclasses import replace
from functools import partial
from typing import Literal
from uuid import UUID

import pytest

import httpx
from posthoganalytics.ai.evaluations import EvaluationItem, EvaluationResult
from pydantic import SecretStr

from products.posthog_ai.eval_harness import offline_results
from products.posthog_ai.eval_harness.engines.types import EvalSummary
from products.posthog_ai.eval_harness.harness import reporting
from products.posthog_ai.eval_harness.harness.offline_delivery import OfflineEvalDelivery
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter
from products.posthog_ai.eval_harness.offline_results import (
    OfflineEvalPublisher,
    OfflineEvalSettings,
    OfflineEvalSuite,
    OfflineEvalUpload,
)
from products.posthog_ai.eval_harness.test.offline_api import OfflineServer

STARTED_AT = "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["disabled: missing configuration", "upload queued", "upload failed", "uploaded"])
async def test_offline_status_links_only_uploaded_results(capsys: pytest.CaptureFixture[str], status: str) -> None:
    reporter = ProgressReporter(total_suites=1)
    await reporter.record_summary(
        "example", EvalSummary(engine_name="braintrust", experiment_name="example", scores={})
    )
    offline_url = "https://posthog.example.com/project/123/ai-evals/evaluations/offline/experiments/example"
    await reporter.record_posthog_offline_result("example", status, url=offline_url if status == "uploaded" else None)
    capsys.readouterr()

    reporter.print_final_summary([], exit_code=0, fail_under=None, duration_seconds=0)

    output = capsys.readouterr().out
    if status == "uploaded":
        assert f"PostHog: {offline_url}" in output
        assert "PostHog offline:" not in output
    else:
        assert "PostHog:" not in output
        assert f"PostHog offline: {status}" in output


def _upload(index: int) -> OfflineEvalUpload:
    return OfflineEvalUpload(
        host="https://posthog.example.com",
        project_id=123,
        experiment_name=f"experiment-{index}",
        experiment={
            "id": str(UUID(int=index)),
            "started_at": STARTED_AT,
            "expected_item_count": 0,
            "expected_result_count": 0,
        },
        results=(),
    )


def _receipt(request: httpx.Request, servers: dict[str, OfflineServer]) -> httpx.Response:
    action = request.url.path.endswith(("/upload/", "/complete/", "/fail/"))
    experiment_id = request.url.path.split("/")[-3] if action else json.loads(request.content)["id"]
    return servers.setdefault(experiment_id, OfflineServer()).respond(request)


def _publisher(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
) -> OfflineEvalPublisher:
    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)))
    return OfflineEvalPublisher(
        OfflineEvalSettings(
            host="https://posthog.example.com",
            project_id=123,
            api_key=SecretStr("test-only-token"),
            scorer_versions={},
            max_retries=0,
        ),
        OfflineEvalSuite(key="example/suite", project_id=123, scorer_kinds={}, scorer_versions={}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [False, True])
async def test_delivery_limits_queued_work_without_waiting_for_uploads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], pause: bool
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    requests: list[httpx.Request] = []
    servers: dict[str, OfflineServer] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            started.set()
            await release.wait()
        elif pause and len(requests) == 3:
            second_started.set()
            await release_second.wait()
        return _receipt(request, servers)

    publisher = _publisher(monkeypatch, respond)
    uploads = [_upload(index) for index in (1, 2, 3)]
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=3), max_concurrency=1, max_pending=2)

    assert delivery.submit(publisher, uploads[0])
    assert delivery.submit(publisher, uploads[1])
    assert not delivery.submit(publisher, uploads[2])
    await asyncio.wait_for(started.wait(), timeout=5)
    assert len(requests) == 1
    release.set()
    if pause:
        await asyncio.wait_for(second_started.wait(), timeout=5)
        await delivery.pause()
        assert not delivery.submit(publisher, uploads[2])
        release_second.set()
    await delivery.drain()

    assert [request.url.path.endswith("/complete/") for request in requests] == (
        [False, True, False, False, True] if pause else [False, True, False, True]
    )
    if pause:
        assert requests[2].content == requests[3].content
    assert not delivery.submit(publisher, uploads[2])
    output = capsys.readouterr().out
    assert output.count("POSTHOG OFFLINE") == 2
    assert "experiment-1  https://posthog.example.com/project/123/" in output
    assert "experiment-2  https://posthog.example.com/project/123/" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [200, 403])
@pytest.mark.parametrize("shutdown", ["pause", "deadline", "interrupt"])
async def test_finished_uploads_are_not_retried_or_marked_interrupted_while_reporting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    http_status: int,
    shutdown: Literal["pause", "deadline", "interrupt"],
) -> None:
    report_started = asyncio.Event()
    report_finished = asyncio.Event()
    release_report = threading.Event()
    loop = asyncio.get_running_loop()
    emit = reporting._emit
    requests: list[httpx.Request] = []
    servers: dict[str, OfflineServer] = {}

    def blocked_emit(text: str) -> None:
        loop.call_soon_threadsafe(report_started.set)
        if not release_report.wait(timeout=5):
            raise TimeoutError("Report was not released")
        emit(text)
        loop.call_soon_threadsafe(report_finished.set)

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _receipt(request, servers) if http_status == 200 else httpx.Response(http_status, json={})

    monkeypatch.setattr(reporting, "_emit", blocked_emit)
    publisher = _publisher(monkeypatch, respond)
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=1))
    assert delivery.submit(publisher, _upload(1))
    try:
        await asyncio.wait_for(report_started.wait(), timeout=5)
        if shutdown == "pause":
            await asyncio.wait_for(delivery.pause(), timeout=5)
        elif shutdown == "deadline":
            await asyncio.wait_for(delivery.drain(timeout=0), timeout=5)
        else:
            await asyncio.wait_for(delivery.cancel(), timeout=5)
    finally:
        release_report.set()
    await delivery.drain()
    await asyncio.wait_for(report_finished.wait(), timeout=5)

    assert len(requests) == (2 if http_status == 200 else 1)
    output = capsys.readouterr().out
    assert output.count("POSTHOG OFFLINE") == 1
    assert "upload interrupted" not in output
    assert "shutdown deadline exceeded" not in output
    if http_status == 200:
        assert "experiment-1  https://posthog.example.com/project/123/" in output
    else:
        assert "upload failed:" in output
        assert "Results were not saved for retry." in output
        assert "403" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", ["pause", "deadline", "interrupt", "tag_timeout"])
async def test_completed_upload_stays_successful_when_tagging_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    shutdown: str,
) -> None:
    monkeypatch.setattr(offline_results.logger, "disabled", False)
    caplog.set_level("WARNING", logger=offline_results.__name__)
    tag_started = asyncio.Event()
    release_tag = asyncio.Event()
    requests: list[httpx.Request] = []
    server = OfflineServer()

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            tag_started.set()
            await release_tag.wait()
        return server.respond(request)

    publisher = _publisher(monkeypatch, respond)
    reporter = ProgressReporter(total_suites=1)
    await reporter.record_summary(
        "experiment-1", EvalSummary(engine_name="braintrust", experiment_name="experiment-1", scores={})
    )
    delivery = OfflineEvalDelivery(reporter)
    if shutdown == "tag_timeout":
        monkeypatch.setattr(offline_results, "TAG_TIMEOUT_SECONDS", 0)
    assert delivery.submit(publisher, replace(_upload(1), tags=("team:example",)))
    if shutdown != "tag_timeout":
        await asyncio.wait_for(tag_started.wait(), timeout=5)
        if shutdown == "pause":
            await delivery.pause()
            release_tag.set()
        elif shutdown == "deadline":
            await delivery.drain(timeout=0)
        else:
            await delivery.cancel()
    await delivery.drain()

    reporter.print_final_summary([], exit_code=0, fail_under=None, duration_seconds=0)
    output = capsys.readouterr().out
    assert server.status == "completed"
    assert sum(request.url.path.endswith("/complete/") for request in requests) == 1
    assert output.count("POSTHOG OFFLINE") == 1
    assert "PostHog: https://posthog.example.com/project/123/" in output
    assert "upload failed" not in output
    if shutdown == "tag_timeout":
        assert "tagging timed out" in caplog.text
    elif shutdown != "pause":
        assert "tag update interrupted" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", ["deadline", "interrupt", "before_start", "paused"])
async def test_shutdown_cancels_active_and_waiting_uploads_and_reports_unsaved_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    shutdown: Literal["deadline", "interrupt", "before_start", "paused"],
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()
    blocked = asyncio.Event()
    requests: list[httpx.Request] = []
    servers: dict[str, OfflineServer] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        started.set()
        try:
            await blocked.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _receipt(request, servers)

    publisher = _publisher(monkeypatch, respond)
    uploads = [_upload(index) for index in (1, 2)]
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=2), max_concurrency=1)
    for upload in uploads:
        assert delivery.submit(publisher, upload)

    if shutdown != "before_start":
        await asyncio.wait_for(started.wait(), timeout=5)
    if shutdown == "paused":
        await delivery.pause()
        assert capsys.readouterr().out == ""
    if shutdown == "deadline":
        await delivery.drain(timeout=0)
    else:
        await delivery.cancel()

    assert len(requests) == (0 if shutdown == "before_start" else 1)
    assert cancelled.is_set() is (shutdown != "before_start")
    output = capsys.readouterr().out
    assert output.count("upload failed:") == 2
    assert output.count("Results were not saved for retry.") == 2
    for upload in uploads:
        assert f"POSTHOG OFFLINE  {upload.experiment_name}" in output
    await delivery.drain()
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_default_delivery_budget_allows_request_timeout_retries_through_completion(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock_offset = 0.0
    loop = asyncio.get_running_loop()
    original_time = loop.time
    monkeypatch.setattr(loop, "time", lambda: original_time() + clock_offset)
    monkeypatch.setattr("posthoganalytics.ai.evaluations._transport.random.uniform", lambda *_: 1.2)
    attempts: dict[str, int] = {}
    server = OfflineServer()

    async def advance(seconds: float) -> None:
        nonlocal clock_offset
        clock_offset += seconds
        resumed = asyncio.Event()
        loop.call_later(0, resumed.set)
        await resumed.wait()

    async def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        attempts[path] = attempts.get(path, 0) + 1
        await advance(settings.request_timeout)
        if attempts[path] <= settings.max_retries:
            raise httpx.ReadTimeout("Synthetic timeout", request=request)
        return server.respond(request)

    monkeypatch.setattr("posthoganalytics.ai.evaluations._transport.asyncio.sleep", advance)
    monkeypatch.setattr(httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)))
    settings = OfflineEvalSettings(
        host="https://posthog.example.com", project_id=123, api_key=SecretStr("test"), scorer_versions={}
    )
    publisher = OfflineEvalPublisher(
        settings, OfflineEvalSuite(key="test/suite", project_id=123, scorer_kinds={}, scorer_versions={})
    )
    upload = replace(
        _upload(1),
        experiment={"id": str(UUID(int=1)), "started_at": STARTED_AT},
        results=(EvaluationResult(item=EvaluationItem(id=UUID(int=2)), scorer_version_id=UUID(int=3), value=1),),
    )
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=1))
    assert delivery.submit(publisher, upload)
    await delivery.drain()

    assert server.status == "completed"
    assert len(server.results) == 1
    assert len(attempts) == 3
    assert all(count == settings.max_retries + 1 for count in attempts.values())
    assert "upload failed:" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_upload_deadline_reports_unsaved_results_before_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[httpx.Request] = []
    servers: dict[str, OfflineServer] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _receipt(request, servers)

    publisher = _publisher(monkeypatch, respond)
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=1), upload_timeout=0)
    assert delivery.submit(publisher, _upload(1))
    await delivery.drain(timeout=5)

    assert requests == []
    output = capsys.readouterr().out
    assert "upload failed: upload deadline exceeded" in output
    assert "Results were not saved for retry." in output


@pytest.mark.asyncio
async def test_rejected_delivery_does_not_prevent_other_uploads(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[httpx.Request] = []
    servers: dict[str, OfflineServer] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if not request.url.path.endswith("/complete/") and json.loads(request.content)["name"] == "experiment-1":
            return httpx.Response(403, json={"detail": "Access denied"})
        return _receipt(request, servers)

    publisher = _publisher(monkeypatch, respond)
    uploads = [_upload(index) for index in (1, 2)]
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=2), max_concurrency=1)
    for upload in uploads:
        assert delivery.submit(publisher, upload)
    await delivery.drain()

    assert sum(request.url.path.endswith("/complete/") for request in requests) == 1
    output = capsys.readouterr().out
    assert "POSTHOG OFFLINE  experiment-1  upload failed:" in output
    assert "Results were not saved for retry." in output
    assert "POSTHOG OFFLINE  experiment-2  https://posthog.example.com/project/123/" in output
