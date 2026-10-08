import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus import emailoctopus
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus import (
    EMAILOCTOPUS_BASE_URL as BASE,
    EmailOctopusResumeConfig,
    _base_url_for_version,
    _build_child_params,
    _format_incremental_value,
    emailoctopus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.settings import (
    CAMPAIGN_REPORT_STATUSES,
    EMAILOCTOPUS_ENDPOINTS,
    EmailOctopusFanOut,
)


def _fanout(endpoint: str) -> EmailOctopusFanOut:
    fanout = EMAILOCTOPUS_ENDPOINTS[endpoint].fanout
    assert fanout is not None
    return fanout


CONTACTS_FANOUT = _fanout("contacts")

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the emailoctopus module.
EO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus.make_tracked_session"
)


def _resp(body: dict[str, Any], status: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "http://test"
    return resp


def _make_manager(resume_state: EmailOctopusResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, page_map: dict[str, Any], calls: list[tuple[str, Any]] | None = None) -> None:
    """Route each request to a canned response keyed by url (+ status param for contacts).

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy at
    prepare_request time. ``send`` returns the response for the last prepared request, matching how
    the client prepares-then-sends each page in lockstep.
    """
    session.headers = {}
    state: dict[str, Any] = {"key": None}

    def _prepare(request: Any) -> mock.MagicMock:
        url = request.url
        params = dict(request.params or {})
        if calls is not None:
            calls.append((url, params))
        key = f"{url}?status={params['status']}" if "status" in params else url
        state["key"] = key
        prepared = mock.MagicMock()
        prepared.url = url
        return prepared

    def _send(prepared: Any, **kwargs: Any) -> requests.Response:
        result = page_map[state["key"]]
        if isinstance(result, Exception):
            raise result
        return result

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, api_version: str = "v2", **kwargs: Any) -> Any:
    return emailoctopus_source(
        api_key="eo_key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        api_version=api_version,
        **kwargs,
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("microseconds_dropped", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45Z"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2024-01-19T12:14:28Z", "2024-01-19T12:14:28Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildChildParams:
    @parameterized.expand(
        [
            ("last_updated", "last_updated_at", "last_updated_at.gte"),
            ("created", "created_at", "created_at.gte"),
        ]
    )
    def test_server_side_filter(self, _name: str, field: str, expected_param: str) -> None:
        params = _build_child_params(
            CONTACTS_FANOUT, "subscribed", incremental_field=field, filter_value="2026-01-01T00:00:00Z"
        )
        assert params[expected_param] == "2026-01-01T00:00:00Z"
        assert params["status"] == "subscribed"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(EO_SESSION_PATCH, return_value=session):
            assert validate_credentials("eo_key") is expected

    def test_tracked_session_redacts_api_key(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(EO_SESSION_PATCH, return_value=session) as make_session:
            validate_credentials("eo_secret")
        # The key must be passed as a redaction value so it can't leak into tracked HTTP logs.
        make_session.assert_called_once_with(redact_values=("eo_secret",))


class TestApiVersionDispatch:
    # EmailOctopus serves every version from the one REST host, so both supported labels — and any
    # undeclared pin honored verbatim by resolve_api_version — must resolve to it.
    @parameterized.expand([("v1",), ("v2",), ("some-undeclared-label",)])
    def test_base_url_resolves_to_rest_host(self, api_version: str) -> None:
        assert _base_url_for_version(api_version) == BASE

    @parameterized.expand([("v1",), ("v2",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_threads_version_into_request_host(self, api_version: str, MockSession) -> None:
        # Route each version to a distinct sentinel host so the assertion fails if the version stops
        # being threaded into the base-URL selection (e.g. reverts to a hardcoded host).
        session = MockSession.return_value
        sentinel = f"https://host-{api_version}.test"
        calls: list[tuple[str, Any]] = []
        _wire(session, {f"{sentinel}/lists": _resp({"data": [{"id": "L1"}], "paging": {"next": None}})}, calls)

        with mock.patch.object(emailoctopus, "_base_url_for_version", lambda v: f"https://host-{v}.test"):
            _rows(_source("lists", _make_manager(), api_version=api_version))

        assert calls
        assert all(url.startswith(sentinel) for url, _ in calls)


class TestHostPinning:
    @parameterized.expand(
        [
            ("top_level", "lists", f"{BASE}/lists"),
            ("fan_out_child", "list_tags", f"{BASE}/lists/L1/tags"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_url_is_refused_before_the_request_goes_out(
        self, _name: str, endpoint: str, paged_url: str, MockSession
    ) -> None:
        session = MockSession.return_value
        # Every request carries the customer's API key as a bearer header, and this source follows
        # `paging.next.url` verbatim. A spoofed next URL must be refused before the credential
        # leaves the process.
        evil_url = "https://evil.example.com/lists?starting_after=cur1"
        _wire(
            session,
            {
                f"{BASE}/lists": _resp(
                    {
                        "data": [{"id": "L1"}],
                        "paging": {"next": {"url": evil_url if endpoint == "lists" else None}},
                    }
                ),
                paged_url: _resp({"data": [{"tag": "vip"}], "paging": {"next": {"url": evil_url}}}),
            },
        )

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source(endpoint, _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_url_is_refused(self, MockSession) -> None:
        session = MockSession.return_value
        # Resume state is read back from Redis, so a poisoned cursor is seeded straight into the
        # paginator. Host pinning covers that seed too.
        evil_url = "https://evil.example.com/campaigns?starting_after=cur5"
        _wire(session, {evil_url: _resp({"data": [], "paging": {"next": None}})})

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("campaigns", _make_manager(EmailOctopusResumeConfig(next_url=evil_url))))


class TestContactsFanOut:
    def _one_list_pages(self, contacts: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        pages: dict[str, Any] = {f"{BASE}/lists": _resp({"data": [{"id": "L1"}], "paging": {"next": None}})}
        for status in ("subscribed", "unsubscribed", "pending"):
            pages[f"{BASE}/lists/L1/contacts?status={status}"] = _resp(
                {"data": contacts.get(status, []), "paging": {"next": None}}
            )
        return pages

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_applies_server_side_incremental_filter_on_every_status(self, MockSession) -> None:
        session = MockSession.return_value
        calls: list[tuple[str, Any]] = []
        _wire(session, self._one_list_pages({}), calls)

        _rows(
            _source(
                "contacts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="last_updated_at",
            )
        )
        contact_calls = [params for url, params in calls if "contacts" in url]
        assert contact_calls
        assert all(params["last_updated_at.gte"] == "2026-01-01T00:00:00Z" for params in contact_calls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_404_error_propagates(self, MockSession) -> None:
        session = MockSession.return_value
        pages = self._one_list_pages({})
        # A non-404 client error is not swallowed by the 404 skip — it fails the sync.
        pages[f"{BASE}/lists/L1/contacts?status=subscribed"] = _resp({}, status=403)
        _wire(session, pages)

        with pytest.raises(requests.HTTPError):
            _rows(_source("contacts", _make_manager()))


class TestCampaignReportsFanOut:
    def _pages(
        self,
        campaigns: list[dict[str, Any]],
        rows_by_status: dict[str, list[dict[str, Any]]] | None = None,
        campaign_id: str = "C1",
    ) -> dict[str, Any]:
        pages: dict[str, Any] = {f"{BASE}/campaigns": _resp({"data": campaigns, "paging": {"next": None}})}
        for status in CAMPAIGN_REPORT_STATUSES:
            pages[f"{BASE}/campaigns/{campaign_id}/reports?status={status}"] = _resp(
                {"status": status, "data": (rows_by_status or {}).get(status, []), "paging": {"next": None}}
            )
        return pages

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_attaches_campaign_id_and_the_requested_status(self, MockSession) -> None:
        session = MockSession.return_value
        # The envelope states the status once and `data_selector` drops it, so without the attach
        # step the eight walks would be indistinguishable in the table.
        _wire(
            session,
            self._pages(
                [{"id": "C1", "status": "sent"}],
                {"opened": [{"contact_id": "ct1", "occurred_at": "2026-01-02T03:04:05+00:00"}]},
            ),
        )
        rows = _rows(_source("campaign_reports", _make_manager()))
        assert rows == [
            {
                "contact_id": "ct1",
                "occurred_at": "2026-01-02T03:04:05+00:00",
                "campaign_id": "C1",
                "status": "opened",
            }
        ]

    @parameterized.expand([("draft",), ("error",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_campaigns_that_never_sent(self, campaign_status: str, MockSession) -> None:
        session = MockSession.return_value
        calls: list[tuple[str, Any]] = []
        # A campaign that never sent has no report. Fanning out over it would spend eight requests
        # per sync on a rejection we could not tell apart from a genuinely malformed one.
        _wire(session, self._pages([{"id": "C1", "status": campaign_status}]), calls)

        rows = _rows(_source("campaign_reports", _make_manager()))

        assert rows == []
        assert not [url for url, _ in calls if "/reports" in url]


class TestUnpaginatedCampaignFanOuts:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_links_attach_campaign_id_and_stop_after_one_page(self, MockSession) -> None:
        session = MockSession.return_value
        calls: list[tuple[str, Any]] = []
        # The links endpoint takes no pagination params and returns no `paging` block; a next-URL
        # paginator would have nothing to follow, so the walk must terminate on the first response.
        _wire(
            session,
            {
                f"{BASE}/campaigns": _resp({"data": [{"id": "C1", "status": "sent"}], "paging": {"next": None}}),
                f"{BASE}/campaigns/C1/reports/links": _resp(
                    {"data": [{"url": "https://example.com/promo-1", "clicked_total": 10, "clicked_unique": 7}]}
                ),
            },
            calls,
        )
        rows = _rows(_source("campaign_report_links", _make_manager()))
        assert rows == [
            {
                "url": "https://example.com/promo-1",
                "clicked_total": 10,
                "clicked_unique": 7,
                "campaign_id": "C1",
            }
        ]
        assert len([url for url, _ in calls if url.endswith("/links")]) == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("lists", ["id"], "created_at"),
            ("campaigns", ["id"], "created_at"),
            ("contacts", ["list_id", "id"], "created_at"),
            ("campaign_reports", ["campaign_id", "status", "contact_id"], "occurred_at"),
            ("campaign_report_summaries", ["id"], None),
            ("campaign_report_links", ["campaign_id", "url"], None),
            ("list_tags", ["list_id", "tag"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], partition_key: str | None
    ) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        assert EMAILOCTOPUS_ENDPOINTS[endpoint].partition_key == partition_key
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [partition_key]
