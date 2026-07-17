from datetime import UTC, date, datetime
from typing import Any, Optional

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly import (
    CALENDLY_BASE_URL,
    CalendlyResumeConfig,
    _build_initial_params,
    _format_datetime,
    calendly_source,
    get_current_organization,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

ORG_URI = "https://api.calendly.com/organizations/ABC123"


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Optional[dict] = None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = str(self._json)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"{self.status_code} Client Error for url: {CALENDLY_BASE_URL}")


class FakeSession:
    """Returns queued responses in order for each .get() call."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, **_kwargs: Any) -> FakeResponse:
        self.requested_urls.append(url)
        return self._responses.pop(0)


class StubResumeManager(ResumableSourceManager[CalendlyResumeConfig]):
    # Overrides every method `get_rows` touches, so the Redis-bound base `__init__` is skipped.
    def __init__(self, resume_state: Optional[CalendlyResumeConfig] = None):
        self._resume_state = resume_state
        self.saved_states: list[CalendlyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[CalendlyResumeConfig]:
        return self._resume_state

    def save_state(self, data: CalendlyResumeConfig) -> None:
        self.saved_states.append(data)


def _users_me_response() -> FakeResponse:
    return FakeResponse(200, {"resource": {"current_organization": ORG_URI}})


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000000Z"),
            ("string_passthrough", "2026-03-04T00:00:00.000000Z", "2026-03-04T00:00:00.000000Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset_in_output(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestBuildInitialParams:
    def test_scope_param_and_count_present(self) -> None:
        params = _build_initial_params(CALENDLY_ENDPOINTS["event_types"], ORG_URI, False, None)

        assert params["organization"] == ORG_URI
        assert params["count"] == 100
        assert "min_start_time" not in params

    def test_scheduled_events_adds_sort_and_no_filter_without_incremental(self) -> None:
        params = _build_initial_params(CALENDLY_ENDPOINTS["scheduled_events"], ORG_URI, False, None)

        assert params["sort"] == "start_time:asc"
        assert "min_start_time" not in params

    def test_scheduled_events_adds_min_start_time_when_incremental(self) -> None:
        params = _build_initial_params(
            CALENDLY_ENDPOINTS["scheduled_events"],
            ORG_URI,
            True,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert params["min_start_time"] == "2026-01-01T00:00:00.000000Z"

    def test_non_incremental_endpoint_never_adds_filter(self) -> None:
        params = _build_initial_params(
            CALENDLY_ENDPOINTS["event_types"], ORG_URI, True, datetime(2026, 1, 1, tzinfo=UTC)
        )

        assert "min_start_time" not in params


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = FakeSession([FakeResponse(status_code)])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly.make_tracked_session",
            return_value=session,
        ):
            assert validate_credentials("token") is expected

    def test_validate_credentials_swallows_exceptions(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly.make_tracked_session",
            side_effect=Exception("network down"),
        ):
            assert validate_credentials("token") is False


class TestGetCurrentOrganization:
    def test_parses_org_uri(self) -> None:
        session = FakeSession([_users_me_response()])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly.make_tracked_session",
            return_value=session,
        ):
            assert get_current_organization("token") == ORG_URI


class TestGetRows:
    def _run(self, session: FakeSession, manager: StubResumeManager, endpoint: str = "event_types", **kwargs):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.calendly.calendly.make_tracked_session",
            return_value=session,
        ):
            return list(
                get_rows(
                    token="token",
                    endpoint=endpoint,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )

    def test_paginates_across_pages_following_next_page(self) -> None:
        page1 = FakeResponse(
            200,
            {
                "collection": [{"uri": "a"}, {"uri": "b"}],
                "pagination": {"next_page": f"{CALENDLY_BASE_URL}/event_types?page=2"},
            },
        )
        page2 = FakeResponse(200, {"collection": [{"uri": "c"}], "pagination": {"next_page": None}})
        session = FakeSession([_users_me_response(), page1, page2])
        manager = StubResumeManager()

        batches = self._run(session, manager)

        assert batches == [[{"uri": "a"}, {"uri": "b"}], [{"uri": "c"}]]
        # State saved after the first page yielded, pointing at page 2.
        assert len(manager.saved_states) == 1
        assert manager.saved_states[0].next_url == f"{CALENDLY_BASE_URL}/event_types?page=2"

    def test_empty_collection_yields_nothing(self) -> None:
        session = FakeSession([_users_me_response(), FakeResponse(200, {"collection": [], "pagination": {}})])

        batches = self._run(session, StubResumeManager())

        assert batches == []

    def test_empty_page_mid_pagination_does_not_terminate_early(self) -> None:
        # An empty page that still advertises a next_page must not end the sync.
        empty_page = FakeResponse(
            200, {"collection": [], "pagination": {"next_page": f"{CALENDLY_BASE_URL}/event_types?page=2"}}
        )
        last_page = FakeResponse(200, {"collection": [{"uri": "a"}], "pagination": {"next_page": None}})
        session = FakeSession([_users_me_response(), empty_page, last_page])

        batches = self._run(session, StubResumeManager())

        assert batches == [[{"uri": "a"}]]

    def test_resume_skips_users_me_and_starts_from_saved_url(self) -> None:
        resume_url = f"{CALENDLY_BASE_URL}/event_types?page=5"
        session = FakeSession([FakeResponse(200, {"collection": [{"uri": "z"}], "pagination": {"next_page": None}})])
        manager = StubResumeManager(resume_state=CalendlyResumeConfig(next_url=resume_url))

        batches = self._run(session, manager)

        assert batches == [[{"uri": "z"}]]
        # No /users/me bootstrap call on resume; first request is the saved URL.
        assert session.requested_urls == [resume_url]

    def test_first_request_scopes_to_organization(self) -> None:
        session = FakeSession(
            [_users_me_response(), FakeResponse(200, {"collection": [{"uri": "a"}], "pagination": {}})]
        )

        self._run(session, StubResumeManager())

        # users/me first, then the scoped list request carrying the org URI.
        assert session.requested_urls[0] == f"{CALENDLY_BASE_URL}/users/me"
        assert "organization=" in session.requested_urls[1]


class TestCalendlySource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = calendly_source(
            token="token",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=StubResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == ["uri"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
