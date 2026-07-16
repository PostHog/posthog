from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb import koyeb
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb import (
    PAGE_SIZE,
    USAGE_WINDOW_START,
    KoyebResumeConfig,
    _build_params,
    _format_time_value,
    get_rows,
    koyeb_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import KOYEB_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: KoyebResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[KoyebResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> KoyebResumeConfig | None:
        return self._state

    def save_state(self, data: KoyebResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, responses: list[dict]) -> list[str]:
    """Replace _fetch_page with a queue that returns canned pages in order, recording each URL."""
    calls: list[str] = []
    queue = list(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        calls.append(url)
        return queue.pop(0)

    monkeypatch.setattr(koyeb, "_fetch_page", fake_fetch)
    return calls


def _collect(endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, responses: list[dict], **kwargs: Any):
    calls = _patch_fetch(monkeypatch, responses)
    rows: list[dict] = []
    for batch in get_rows(
        api_token="t",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        should_use_incremental_field=kwargs.get("should_use_incremental_field", False),
        db_incremental_field_last_value=kwargs.get("db_incremental_field_last_value"),
    ):
        rows.extend(batch)
    return rows, calls


class TestFormatTimeValue:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2024, 5, 1, 12, 30, 45), "2024-05-01T12:30:45Z"),
            ("aware_utc", datetime(2024, 5, 1, 12, 30, 45, tzinfo=UTC), "2024-05-01T12:30:45Z"),
            # Non-UTC offsets must be converted, not just re-labelled.
            (
                "aware_offset",
                datetime(2024, 5, 1, 14, 30, 45, tzinfo=timezone(timedelta(hours=2))),
                "2024-05-01T12:30:45Z",
            ),
            ("date", date(2024, 5, 1), "2024-05-01T00:00:00Z"),
            ("string_passthrough", "2024-05-01T00:00:00Z", "2024-05-01T00:00:00Z"),
        ]
    )
    def test_formats_rfc3339_utc(self, _name: str, value: Any, expected: str) -> None:
        assert _format_time_value(value) == expected


class TestBuildParams:
    @parameterized.expand(
        [
            ("plain_endpoint", "apps", None, {"limit": PAGE_SIZE, "offset": 0}),
            # Endpoints with an `order` param are always requested ascending so offset pagination
            # stays stable while rows are appended mid-sync.
            ("ordered_endpoint", "app_events", None, {"limit": PAGE_SIZE, "offset": 0, "order": "asc"}),
            (
                "incremental_instances",
                "instances",
                datetime(2024, 5, 1, tzinfo=UTC),
                {"limit": PAGE_SIZE, "offset": 0, "order": "asc", "starting_time": "2024-05-01T00:00:00Z"},
            ),
            # apps has no server-side time filter, so a watermark must not become a query param.
            (
                "no_time_filter_drops_cutoff",
                "apps",
                datetime(2024, 5, 1, tzinfo=UTC),
                {"limit": PAGE_SIZE, "offset": 0},
            ),
        ]
    )
    def test_build_params(self, _name: str, endpoint: str, cutoff: Any, expected: dict[str, Any]) -> None:
        assert _build_params(KOYEB_ENDPOINTS[endpoint], 0, cutoff) == expected

    def test_usage_details_always_sends_required_window(self) -> None:
        # /v1/usages/details rejects requests without a time window, so both bounds must be present
        # even on a full refresh.
        params = _build_params(KOYEB_ENDPOINTS["usage_details"], 200, None, "2026-01-01T00:00:00Z")
        assert params["starting_time"] == USAGE_WINDOW_START
        assert params["ending_time"] == "2026-01-01T00:00:00Z"
        assert params["offset"] == 200
        assert params["order"] == "asc"


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        response = requests.Response()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(koyeb, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("token")

        assert ok is expected_ok, f"status={status}"
        assert (error is None) is expected_ok, f"status={status}"

    def test_request_exception_is_handled(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(koyeb, "make_tracked_session", lambda *a, **k: session)

        ok, error = validate_credentials("token")
        assert ok is False
        assert error == "boom"


class TestGetRows:
    def test_follows_offset_pagination_with_has_next(self, monkeypatch: Any) -> None:
        responses = [
            {"apps": [{"id": str(i)} for i in range(PAGE_SIZE)], "has_next": True},
            {"apps": [{"id": "last"}], "has_next": False},
        ]
        rows, calls = _collect("apps", _FakeResumableManager(), monkeypatch, responses)

        assert len(rows) == PAGE_SIZE + 1
        assert "offset=0" in calls[0]
        assert f"offset={PAGE_SIZE}" in calls[1]
        assert len(calls) == 2

    def test_short_page_without_has_next_terminates(self, monkeypatch: Any) -> None:
        # Some replies (e.g. secrets) carry no has_next; a short page is the end-of-list signal.
        responses = [{"secrets": [{"id": "s1"}, {"id": "s2"}]}]
        rows, calls = _collect("secrets", _FakeResumableManager(), monkeypatch, responses)

        assert [r["id"] for r in rows] == ["s1", "s2"]
        assert len(calls) == 1

    def test_full_page_without_has_next_fetches_until_empty_page(self, monkeypatch: Any) -> None:
        # An exact-multiple total with no has_next only stops on the following empty page.
        responses: list[dict] = [
            {"secrets": [{"id": str(i)} for i in range(PAGE_SIZE)]},
            {"secrets": []},
        ]
        rows, calls = _collect("secrets", _FakeResumableManager(), monkeypatch, responses)

        assert len(rows) == PAGE_SIZE
        assert len(calls) == 2

    def test_saves_offset_after_each_completed_page(self, monkeypatch: Any) -> None:
        responses = [
            {"apps": [{"id": str(i)} for i in range(PAGE_SIZE)], "has_next": True},
            {"apps": [{"id": str(i)} for i in range(PAGE_SIZE)], "has_next": True},
            {"apps": [{"id": "last"}], "has_next": False},
        ]
        manager = _FakeResumableManager()
        _collect("apps", manager, monkeypatch, responses)

        # No checkpoint after the final page — the walk is complete, nothing left to resume into.
        assert manager.saved == [KoyebResumeConfig(offset=PAGE_SIZE), KoyebResumeConfig(offset=PAGE_SIZE * 2)]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        responses = [{"apps": [{"id": "1"}], "has_next": False}]
        manager = _FakeResumableManager(KoyebResumeConfig(offset=300))
        rows, calls = _collect("apps", manager, monkeypatch, responses)

        assert [r["id"] for r in rows] == ["1"]
        assert "offset=300" in calls[0]

    def test_incremental_instances_sends_starting_time(self, monkeypatch: Any) -> None:
        responses = [{"instances": [{"id": "i1"}], "has_next": False}]
        _, calls = _collect(
            "instances",
            _FakeResumableManager(),
            monkeypatch,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert "starting_time=2024-05-01T00%3A00%3A00Z" in calls[0]
        assert "order=asc" in calls[0]

    def test_full_refresh_instances_omits_starting_time(self, monkeypatch: Any) -> None:
        responses = [{"instances": [{"id": "i1"}], "has_next": False}]
        _, calls = _collect(
            "instances",
            _FakeResumableManager(),
            monkeypatch,
            responses,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
        )

        assert "starting_time" not in calls[0]

    def test_deployment_definition_secrets_are_redacted(self, monkeypatch: Any) -> None:
        # Deployment definitions embed plaintext env values and config-file content; leaving them
        # in place would expose credentials to anyone with warehouse-query access.
        responses = [
            {
                "deployments": [
                    {
                        "id": "d1",
                        "definition": {
                            "env": [
                                {"key": "DB_PASSWORD", "value": "hunter2"},
                                {"key": "API_KEY", "secret": "my-secret-ref"},
                            ],
                            "config_files": [{"path": "/etc/app.conf", "content": "token=abc123"}],
                        },
                    }
                ],
                "has_next": False,
            }
        ]
        rows, _ = _collect("deployments", _FakeResumableManager(), monkeypatch, responses)

        env = rows[0]["definition"]["env"]
        assert env[0] == {"key": "DB_PASSWORD", "value": "[redacted by PostHog]"}
        # A secret *reference* is just a name, not the value, so it survives untouched.
        assert env[1] == {"key": "API_KEY", "secret": "my-secret-ref"}
        assert rows[0]["definition"]["config_files"][0] == {
            "path": "/etc/app.conf",
            "content": "[redacted by PostHog]",
        }

    def test_non_deployment_rows_pass_through_untouched(self, monkeypatch: Any) -> None:
        # Only definition-bearing endpoints are scrubbed; a stray `value`/`content` elsewhere stays.
        responses = [{"secrets": [{"id": "s1", "value": "keep-me"}]}]
        rows, _ = _collect("secrets", _FakeResumableManager(), monkeypatch, responses)

        assert rows[0] == {"id": "s1", "value": "keep-me"}

    def test_sample_capture_disabled_only_for_secret_scrubbed_endpoints(self, monkeypatch: Any) -> None:
        # HTTP sample capture stores the raw response body before the definition scrub runs, so
        # secret-scrubbed endpoints must opt their session out of capture while the rest stay in.
        session_kwargs: list[dict] = []

        def fake_session(**kwargs: Any) -> Any:
            session_kwargs.append(kwargs)
            return MagicMock()

        monkeypatch.setattr(koyeb, "make_tracked_session", fake_session)
        _patch_fetch(monkeypatch, [{"deployments": [], "has_next": False}, {"apps": [], "has_next": False}])
        for endpoint in ("deployments", "apps"):
            list(
                get_rows(
                    api_token="t",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )

        assert session_kwargs == [{"capture": False}, {"capture": True}]

    def test_uses_response_data_key_per_endpoint(self, monkeypatch: Any) -> None:
        # Event streams all return their rows under "events", not the endpoint name.
        responses = [{"events": [{"id": "e1"}], "has_next": False}]
        rows, calls = _collect("deployment_events", _FakeResumableManager(), monkeypatch, responses)

        assert [r["id"] for r in rows] == ["e1"]
        assert "/v1/deployment_events" in calls[0]


class TestKoyebSource:
    @parameterized.expand([(name,) for name in KOYEB_ENDPOINTS])
    def test_source_response_per_endpoint(self, endpoint: str) -> None:
        config = KOYEB_ENDPOINTS[endpoint]
        response = koyeb_source(
            api_token="t",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_usage_details_composite_primary_key(self) -> None:
        # Usage rows have no id; dropping either half of the composite key would multi-match merges.
        assert KOYEB_ENDPOINTS["usage_details"].primary_keys == ["instance_id", "started_at"]
