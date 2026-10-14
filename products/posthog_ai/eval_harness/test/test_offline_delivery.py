from __future__ import annotations

import json
import asyncio
import threading
from collections.abc import Callable, Coroutine
from functools import partial
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest

import httpx
from pydantic import SecretStr

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


def _save_upload(directory: Path, index: int) -> Path:
    path = directory / f"upload-{index}.json"
    OfflineEvalUpload(
        host="https://posthog.example.com",
        project_id=123,
        experiment_name=f"experiment-{index}",
        experiment={
            "id": str(UUID(int=index)),
            "started_at": STARTED_AT,
            "expected_item_count": 0,
            "expected_result_count": 0,
        },
        items=(),
        results=(),
    ).save(path)
    return path


def _receipt(request: httpx.Request, servers: dict[str, OfflineServer]) -> httpx.Response:
    complete = request.url.path.endswith("/complete/")
    experiment_id = request.url.path.split("/")[-3] if complete else json.loads(request.content)["id"]
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
        OfflineEvalSuite(key="example/suite", scorer_kinds={}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [False, True])
async def test_delivery_limits_queued_work_without_waiting_for_uploads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], pause: bool
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
    paths = [_save_upload(tmp_path, index) for index in (1, 2, 3)]
    saved = [path.read_bytes() for path in paths]
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=3), max_concurrency=1, max_pending=2)

    assert delivery.submit(publisher, paths[0], "experiment-1")
    assert delivery.submit(publisher, paths[1], "experiment-2")
    assert not delivery.submit(publisher, paths[2], "experiment-3")
    await asyncio.wait_for(started.wait(), timeout=5)
    assert len(requests) == 1
    release.set()
    if pause:
        await asyncio.wait_for(second_started.wait(), timeout=5)
        await delivery.pause()
        assert not delivery.submit(publisher, paths[2], "experiment-3")
        release_second.set()
    await delivery.drain()

    assert [request.url.path.endswith("/complete/") for request in requests] == (
        [False, True, False, False, True] if pause else [False, True, False, True]
    )
    if pause:
        assert requests[2].content == requests[3].content
    assert [path.read_bytes() for path in paths] == saved
    assert not delivery.submit(publisher, paths[2], "experiment-3")
    output = capsys.readouterr().out
    assert output.count("POSTHOG OFFLINE") == 2
    assert "experiment-1  https://posthog.example.com/project/123/" in output
    assert "experiment-2  https://posthog.example.com/project/123/" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [200, 403])
@pytest.mark.parametrize("shutdown", ["pause", "deadline", "interrupt"])
async def test_finished_uploads_are_not_replayed_or_marked_interrupted_while_reporting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
    path = _save_upload(tmp_path, 1)
    saved = path.read_bytes()
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=1))
    assert delivery.submit(publisher, path, "experiment-1")
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
    assert path.read_bytes() == saved
    output = capsys.readouterr().out
    assert output.count("POSTHOG OFFLINE") == 1
    assert "upload interrupted" not in output
    assert "shutdown deadline exceeded" not in output
    if http_status == 200:
        assert "experiment-1  https://posthog.example.com/project/123/" in output
    else:
        assert "upload pending:" in output
        assert "403" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", ["deadline", "interrupt", "before_start", "paused"])
async def test_shutdown_cancels_active_and_waiting_uploads_and_preserves_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
    paths = [_save_upload(tmp_path, index) for index in (1, 2)]
    saved = [path.read_bytes() for path in paths]
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=2), max_concurrency=1)
    for index, path in enumerate(paths, start=1):
        assert delivery.submit(publisher, path, f"experiment-{index}")

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
    assert [path.read_bytes() for path in paths] == saved
    output = capsys.readouterr().out
    assert output.count("upload pending:") == 2
    for path in paths:
        assert f"Saved requests: {path}" in output
    await delivery.drain()
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_upload_deadline_preserves_saved_results_before_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    requests: list[httpx.Request] = []
    servers: dict[str, OfflineServer] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _receipt(request, servers)

    publisher = _publisher(monkeypatch, respond)
    path = _save_upload(tmp_path, 1)
    saved = path.read_bytes()
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=1), upload_timeout=0)
    assert delivery.submit(publisher, path, "experiment-1")
    await delivery.drain()

    assert requests == []
    assert path.read_bytes() == saved
    output = capsys.readouterr().out
    assert "upload pending: upload deadline exceeded" in output
    assert f"Saved requests: {path}" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid_artifact", "rejected_upload"])
async def test_failed_delivery_does_not_discard_artifacts_or_prevent_other_uploads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: Literal["invalid_artifact", "rejected_upload"],
) -> None:
    requests: list[httpx.Request] = []
    servers: dict[str, OfflineServer] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if not request.url.path.endswith("/complete/") and json.loads(request.content)["name"] == "experiment-1":
            return httpx.Response(403, json={"detail": "Access denied"})
        return _receipt(request, servers)

    publisher = _publisher(monkeypatch, respond)
    paths = [_save_upload(tmp_path, index) for index in (1, 2)]
    if failure == "invalid_artifact":
        paths[0].write_text("invalid-json")
    saved = [path.read_bytes() for path in paths]
    delivery = OfflineEvalDelivery(ProgressReporter(total_suites=2), max_concurrency=1)
    for index, path in enumerate(paths, start=1):
        assert delivery.submit(publisher, path, f"experiment-{index}")
    await delivery.drain()

    assert sum(request.url.path.endswith("/complete/") for request in requests) == 1
    assert [path.read_bytes() for path in paths] == saved
    output = capsys.readouterr().out
    assert "POSTHOG OFFLINE  experiment-1  upload pending:" in output
    assert f"Saved requests: {paths[0]}" in output
    assert "POSTHOG OFFLINE  experiment-2  https://posthog.example.com/project/123/" in output
