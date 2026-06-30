import pytest

from temporalio.exceptions import ApplicationError

import products.engineering_analytics.backend.logic.job_logs.activity as activity_module
from products.engineering_analytics.backend.logic.job_logs.activity import (
    FetchJobLogInputs,
    fetch_and_emit_job_log_activity,
)

_INPUTS = FetchJobLogInputs(
    team_id=1, integration_id=2, repo="PostHog/posthog", job_id=3, run_id=4, branch="main", conclusion="failure"
)


class _FakeEmitter:
    def __init__(self, *_args, **_kwargs):
        self.archive = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def emit_log_archive(self, lines, **_kwargs):
        self.lines = lines
        return len(lines)


def _patch(monkeypatch, *, acquired=True, archive="l1\nl2\nl3"):
    async def _acquire(_installation_id):
        return acquired

    monkeypatch.setattr(activity_module, "acquire_github_installation", _acquire)
    monkeypatch.setattr(
        activity_module, "_resolve_credentials", lambda _team_id, _integration_id: ("tok", "inst-99", "phc_dest")
    )
    monkeypatch.setattr(activity_module, "fetch_job_log", lambda _repo, _job_id, _token: archive)
    monkeypatch.setattr(activity_module, "JobLogsEmitter", _FakeEmitter)
    monkeypatch.setattr(activity_module.settings, "OTLP_LOGS_INGEST_ENDPOINT", "http://localhost:8010/i/v1/logs")


async def test_emits_and_returns_line_count(monkeypatch):
    _patch(monkeypatch, archive="line one\nline two")
    result = await fetch_and_emit_job_log_activity(_INPUTS)
    assert result == {"status": "emitted", "job_id": 3, "lines": 2}


async def test_raises_and_skips_fetch_when_budget_exhausted(monkeypatch):
    # The gate must stop us before the GitHub call when over the shared budget, and raise (retryable)
    # so Temporal backs off — never silently proceed.
    fetched = {"called": False}

    def _fetch(*_args, **_kwargs):
        fetched["called"] = True
        return "x"

    _patch(monkeypatch, acquired=False)
    monkeypatch.setattr(activity_module, "fetch_job_log", _fetch)
    with pytest.raises(ApplicationError):
        await fetch_and_emit_job_log_activity(_INPUTS)
    assert fetched["called"] is False


async def test_log_unavailable_is_benign(monkeypatch):
    # An expired/purged log (fetch returns None) must report log_unavailable, not crash or emit.
    _patch(monkeypatch)
    monkeypatch.setattr(activity_module, "fetch_job_log", lambda *_args, **_kwargs: None)
    result = await fetch_and_emit_job_log_activity(_INPUTS)
    assert result == {"status": "log_unavailable", "job_id": 3, "lines": 0}


async def test_raises_when_export_disabled(monkeypatch):
    # No Logs endpoint configured: raise (retryable) before fetching, so the failure isn't marked
    # done-and-unretryable and we don't spend egress budget on a job we can't emit.
    fetched = {"called": False}

    def _fetch(*_args, **_kwargs):
        fetched["called"] = True
        return "x"

    _patch(monkeypatch)
    monkeypatch.setattr(activity_module.settings, "OTLP_LOGS_INGEST_ENDPOINT", "")
    monkeypatch.setattr(activity_module, "fetch_job_log", _fetch)
    with pytest.raises(ApplicationError):
        await fetch_and_emit_job_log_activity(_INPUTS)
    assert fetched["called"] is False
