import pytest

from temporalio.exceptions import ApplicationError

import products.engineering_analytics.backend.logic.job_logs.activity as activity_module
from products.engineering_analytics.backend.logic.job_logs.activity import (
    FetchDepotJobLogInputs,
    FetchJobLogInputs,
    _DepotCredentials,
    fetch_and_emit_depot_job_log_activity,
    fetch_and_emit_job_log_activity,
)

_INPUTS = FetchJobLogInputs(
    team_id=1,
    integration_id=2,
    repo="PostHog/posthog",
    job_id=3,
    run_id=4,
    branch="main",
    conclusion="failure",
    job_name="backend-tests",
    workflow_name="Backend CI",
    run_attempt=2,
    head_sha="abc1234",
)

_DEPOT_INPUTS = FetchDepotJobLogInputs(
    team_id=1,
    source_id="0192f0c4-0000-7000-8000-000000000001",
    attempt_id="zf6sbbn2wh",
    run_id=80213453736890,
    job_id=579485267642625,
    repo="PostHog/posthog",
    workflow_name="Backend CI on Depot",
    job_name="Product tests (experiments)",
    run_attempt=1,
    head_sha="abc1234",
)


class _FakeEmitter:
    last_kwargs: dict = {}

    def __init__(self, *_args, **_kwargs):
        self.archive = None
        _FakeEmitter.last_kwargs = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def emit_log_archive(self, lines, **kwargs):
        self.lines = lines
        _FakeEmitter.last_kwargs = kwargs
        return len(lines)


def _patch(monkeypatch, *, acquired=True, archive="l1\nl2\nl3"):
    async def _acquire(_installation_id, **_kwargs):
        return acquired

    monkeypatch.setattr(activity_module, "acquire_github_installation", _acquire)
    monkeypatch.setattr(
        activity_module, "_resolve_credentials", lambda _team_id, _integration_id: ("tok", "inst-99", "phc_dest")
    )
    monkeypatch.setattr(activity_module, "fetch_job_log", lambda _repo, _job_id, _token: archive)
    monkeypatch.setattr(
        activity_module,
        "_resolve_depot_credentials",
        lambda _team_id, _source_id: _DepotCredentials(api_token="depot-tok", log_ingest_token="phc_dest"),
    )
    monkeypatch.setattr(activity_module, "fetch_depot_job_log", lambda _attempt_id, _token: archive)
    monkeypatch.setattr(activity_module, "JobLogsEmitter", _FakeEmitter)
    monkeypatch.setattr(activity_module.settings, "OTLP_LOGS_INGEST_ENDPOINT", "http://localhost:8010/i/v1/logs")


async def test_emits_and_returns_line_count(monkeypatch):
    _patch(monkeypatch, archive="line one\nline two")
    result = await fetch_and_emit_job_log_activity(_INPUTS)
    assert result == {"status": "emitted", "job_id": 3, "lines": 2}
    # The job identity attributes must reach the emitter — dropping one here silently strips it
    # from every stored record, and it can't be backfilled (GitHub logs expire).
    attrs = _FakeEmitter.last_kwargs["attributes"]
    assert attrs["job_name"] == "backend-tests"
    assert attrs["workflow_name"] == "Backend CI"
    assert attrs["run_attempt"] == 2
    assert attrs["head_sha"] == "abc1234"


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


async def test_depot_attempt_fetches_by_attempt_id_and_emits_decoded_ids(monkeypatch):
    # Logs rows join the curated CI views and traces on the decoded integer ids. Emitting Depot's
    # string ids, or swapping run and attempt, leaves every Depot failure log unreachable by run_id.
    _patch(monkeypatch)
    fetched: dict[str, str] = {}

    def _fetch(attempt_id, token):
        fetched.update(attempt_id=attempt_id, token=token)
        return "##[error]boom"

    monkeypatch.setattr(activity_module, "fetch_depot_job_log", _fetch)
    result = await fetch_and_emit_depot_job_log_activity(_DEPOT_INPUTS)
    assert result == {"status": "emitted", "job_id": 579485267642625, "lines": 1}
    assert fetched == {"attempt_id": "zf6sbbn2wh", "token": "depot-tok"}
    assert (_FakeEmitter.last_kwargs["trace_id"], _FakeEmitter.last_kwargs["span_id"]) == (
        80213453736890,
        579485267642625,
    )
    assert _FakeEmitter.last_kwargs["attributes"] == {
        "job_id": 579485267642625,
        "run_id": 80213453736890,
        "repo": "PostHog/posthog",
        "branch": "",
        "conclusion": "failure",
        "job_name": "Product tests (experiments)",
        "workflow_name": "Backend CI on Depot",
        "run_attempt": 1,
        "head_sha": "abc1234",
        "orig_total": 1,
    }


_ACTIVITIES = [
    (fetch_and_emit_job_log_activity, _INPUTS, "fetch_job_log"),
    (fetch_and_emit_depot_job_log_activity, _DEPOT_INPUTS, "fetch_depot_job_log"),
]


@pytest.mark.parametrize("activity_fn, inputs, fetcher", _ACTIVITIES)
async def test_log_unavailable_is_benign(monkeypatch, activity_fn, inputs, fetcher):
    # An expired/purged log (fetch returns None) must report log_unavailable, not crash or emit.
    _patch(monkeypatch)
    monkeypatch.setattr(activity_module, fetcher, lambda *_args, **_kwargs: None)
    result = await activity_fn(inputs)
    assert result == {"status": "log_unavailable", "job_id": inputs.job_id, "lines": 0}


@pytest.mark.parametrize("activity_fn, inputs, fetcher", _ACTIVITIES)
async def test_raises_when_export_disabled(monkeypatch, activity_fn, inputs, fetcher):
    # No Logs endpoint configured: raise (retryable) before fetching, so the failure isn't marked
    # done-and-unretryable and we don't spend egress budget on a job we can't emit.
    fetched = {"called": False}

    def _fetch(*_args, **_kwargs):
        fetched["called"] = True
        return "x"

    _patch(monkeypatch)
    monkeypatch.setattr(activity_module.settings, "OTLP_LOGS_INGEST_ENDPOINT", "")
    monkeypatch.setattr(activity_module, fetcher, _fetch)
    with pytest.raises(ApplicationError):
        await activity_fn(inputs)
    assert fetched["called"] is False
