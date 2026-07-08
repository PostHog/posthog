import base64
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.gorgias import (
    GorgiasResumeConfig,
    get_base_url,
    get_headers,
    get_rows,
    gorgias_source,
    normalize_domain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.settings import (
    ENDPOINTS,
    GORGIAS_ENDPOINTS,
)

GORGIAS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.gorgias"


class _FakeManager(ResumableSourceManager[GorgiasResumeConfig]):
    """Minimal stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, resume_cursor: str | None = None) -> None:
        self._resume_cursor = resume_cursor
        self.saved: list[GorgiasResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_cursor is not None

    def load_state(self) -> GorgiasResumeConfig | None:
        return GorgiasResumeConfig(cursor=self._resume_cursor) if self._resume_cursor else None

    def save_state(self, data: GorgiasResumeConfig) -> None:
        self.saved.append(data)


def _response(status_code: int = 200, json_body: dict | None = None, ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = ok
    response.json.return_value = json_body or {}
    response.text = ""
    return response


class TestNormalizeDomain:
    @parameterized.expand(
        [
            ("bare_subdomain", "acme", "acme"),
            ("full_host", "acme.gorgias.com", "acme"),
            ("https_url", "https://acme.gorgias.com", "acme"),
            ("https_url_with_path", "https://acme.gorgias.com/api/", "acme"),
            ("uppercase_and_spaces", "  ACME  ", "acme"),
            ("trailing_slash", "acme/", "acme"),
        ]
    )
    def test_normalize_domain(self, _name: str, value: str, expected: str) -> None:
        assert normalize_domain(value) == expected

    def test_get_base_url(self) -> None:
        assert get_base_url("acme.gorgias.com") == "https://acme.gorgias.com/api"

    @parameterized.expand(
        [
            # Crafted inputs that would otherwise break out of the .gorgias.com host
            # and redirect the request (and the Basic-auth header) elsewhere.
            ("fragment", "attacker.example.com#"),
            ("query", "169.254.169.254?x="),
            ("userinfo", "user@attacker.example.com"),
            ("port", "attacker.example.com:8080"),
            ("dotted", "evil.com"),
            ("empty", "   "),
            ("leading_hyphen", "-acme"),
        ]
    )
    def test_get_base_url_rejects_unsafe_domains(self, _name: str, domain: str) -> None:
        with pytest.raises(ValueError):
            get_base_url(domain)


class TestHeaders:
    def test_basic_auth_header_is_email_and_api_key(self) -> None:
        headers = get_headers("you@acme.com", "secret-key")
        scheme, _, token = headers["Authorization"].partition(" ")
        assert scheme == "Basic"
        assert base64.b64decode(token).decode() == "you@acme.com:secret-key"
        assert headers["Accept"] == "application/json"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response(status_code=status_code)
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("acme", "you@acme.com", "key")
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_empty_domain_fails_without_request(self) -> None:
        with patch(f"{GORGIAS_MODULE}.make_tracked_session") as mocked:
            valid, error = validate_credentials("   ", "you@acme.com", "key")
        assert valid is False
        assert error is not None
        mocked.assert_not_called()

    def test_unsafe_domain_fails_without_request(self) -> None:
        with patch(f"{GORGIAS_MODULE}.make_tracked_session") as mocked:
            valid, error = validate_credentials("attacker.example.com#", "you@acme.com", "key")
        assert valid is False
        assert error is not None
        mocked.assert_not_called()

    def test_connection_error_is_handled(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            valid, error = validate_credentials("acme", "you@acme.com", "key")
        assert valid is False
        assert error is not None


class TestGetRows:
    def test_paginates_until_next_cursor_is_null(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": "c2"}}),
            _response(json_body={"data": [{"id": 2}], "meta": {"next_cursor": None}}),
        ]
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}]]
        assert session.get.call_count == 2

    def test_saves_cursor_after_yielding_each_batch(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": "c2"}}),
            _response(json_body={"data": [{"id": 2}], "meta": {"next_cursor": None}}),
        ]
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        # Only the page that has a following cursor triggers a save.
        assert [c.cursor for c in manager.saved] == ["c2"]

    def test_resumes_from_saved_cursor(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager(resume_cursor="resume-token")
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        _, kwargs = session.get.call_args
        assert kwargs["params"]["cursor"] == "resume-token"

    def test_passes_explicit_order_by_and_limit(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        _, kwargs = session.get.call_args
        assert kwargs["params"]["order_by"] == "created_datetime:asc"
        assert kwargs["params"]["limit"] == 100
        assert "cursor" not in kwargs["params"]

    def test_empty_first_page_terminates(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager))

        assert batches == []
        assert manager.saved == []


class TestIncrementalSync:
    def _run(self, session: MagicMock, **kwargs):
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            return list(
                get_rows(
                    "acme",
                    "e@acme.com",
                    "key",
                    "tickets",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    incremental_field="updated_datetime",
                    **kwargs,
                )
            )

    def test_incremental_sorts_chosen_field_descending(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        self._run(session, db_incremental_field_last_value=None)

        _, kwargs = session.get.call_args
        assert kwargs["params"]["order_by"] == "updated_datetime:desc"

    def test_first_incremental_sync_walks_all_pages(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_body={
                    "data": [{"id": 2, "updated_datetime": "2023-07-01T00:00:00+00:00"}],
                    "meta": {"next_cursor": "c2"},
                }
            ),
            _response(
                json_body={
                    "data": [{"id": 1, "updated_datetime": "2023-01-01T00:00:00+00:00"}],
                    "meta": {"next_cursor": None},
                }
            ),
        ]
        batches = self._run(session, db_incremental_field_last_value=None)

        assert [item["id"] for batch in batches for item in batch] == [2, 1]
        assert session.get.call_count == 2

    def test_stops_once_page_predates_watermark(self) -> None:
        # Rows arrive newest-first; the third page is never fetched because the second
        # page is entirely older than the watermark.
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_body={
                    "data": [{"id": 3, "updated_datetime": "2023-07-01T00:00:00+00:00"}],
                    "meta": {"next_cursor": "c2"},
                }
            ),
            _response(
                json_body={
                    "data": [{"id": 2, "updated_datetime": "2023-05-01T00:00:00+00:00"}],
                    "meta": {"next_cursor": "c3"},
                }
            ),
            _response(
                json_body={
                    "data": [{"id": 1, "updated_datetime": "2023-04-01T00:00:00+00:00"}],
                    "meta": {"next_cursor": None},
                }
            ),
        ]
        batches = self._run(session, db_incremental_field_last_value=datetime(2023, 6, 1, tzinfo=UTC))

        # The over-the-watermark page is still yielded (merge dedupes), then we stop.
        assert [item["id"] for batch in batches for item in batch] == [3, 2]
        assert session.get.call_count == 2

    def test_unknown_incremental_field_falls_back_to_full_refresh(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(
                get_rows(
                    "acme",
                    "e@acme.com",
                    "key",
                    "tickets",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    incremental_field="not_a_sortable_field",
                    db_incremental_field_last_value=datetime(2023, 6, 1, tzinfo=UTC),
                )
            )

        _, kwargs = session.get.call_args
        assert kwargs["params"]["order_by"] == "created_datetime:asc"

    def test_incremental_field_not_sortable_on_endpoint_falls_back(self) -> None:
        # `users` does not accept `updated_datetime` in order_by; forcing it must not send
        # an order_by Gorgias would reject — fall back to the full-refresh sort instead.
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(
                get_rows(
                    "acme",
                    "e@acme.com",
                    "key",
                    "users",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    incremental_field="updated_datetime",
                    db_incremental_field_last_value=datetime(2023, 6, 1, tzinfo=UTC),
                )
            )

        _, kwargs = session.get.call_args
        assert kwargs["params"]["order_by"] == "created_datetime:asc"

    def test_order_by_persists_across_pages_alongside_cursor(self) -> None:
        # Gorgias' cursor only makes sense within the same sorted list, so order_by must
        # ride along on every follow-up page, not just the first.
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_body={
                    "data": [{"id": 2, "updated_datetime": "2023-07-01T00:00:00+00:00"}],
                    "meta": {"next_cursor": "c2"},
                }
            ),
            _response(
                json_body={
                    "data": [{"id": 1, "updated_datetime": "2023-06-15T00:00:00+00:00"}],
                    "meta": {"next_cursor": None},
                }
            ),
        ]
        self._run(session, db_incremental_field_last_value=None)

        first_params = session.get.call_args_list[0].kwargs["params"]
        second_params = session.get.call_args_list[1].kwargs["params"]
        assert "cursor" not in first_params
        assert first_params["order_by"] == "updated_datetime:desc"
        assert second_params["cursor"] == "c2"
        assert second_params["order_by"] == "updated_datetime:desc"
        assert second_params["limit"] == 100


# Per-endpoint `order_by` enums quoted from the Gorgias API docs (the `.md` reference for
# each list endpoint). This is the external contract our config must not drift from: if an
# endpoint is configured to sort by a field absent here, Gorgias would reject or ignore it.
DOCUMENTED_ORDER_BY_DATETIME_FIELDS: dict[str, set[str]] = {
    "tickets": {"created_datetime", "updated_datetime"},
    "messages": {"created_datetime"},
    "customers": {"created_datetime", "updated_datetime"},
    "users": {"created_datetime"},  # also name/email/role, but no updated_datetime
    "satisfaction_surveys": {"created_datetime"},
    "macros": {"created_datetime", "updated_datetime"},
    "tags": {"created_datetime"},
    "views": {"created_datetime"},
    "teams": {"created_datetime"},
}


class TestApiContract:
    """Pin the endpoint config to the documented Gorgias API so it can't silently drift."""

    def test_sortable_fields_match_documented_api(self) -> None:
        assert {name: set(config.sortable_datetime_fields) for name, config in GORGIAS_ENDPOINTS.items()} == (
            DOCUMENTED_ORDER_BY_DATETIME_FIELDS
        )

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_full_refresh_order_by_is_accepted_by_endpoint(self, endpoint: str) -> None:
        config = GORGIAS_ENDPOINTS[endpoint]
        field, _, direction = config.order_by.partition(":")
        assert field in DOCUMENTED_ORDER_BY_DATETIME_FIELDS[endpoint]
        assert direction in {"asc", "desc"}

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_advertised_incremental_fields_are_sortable(self, endpoint: str) -> None:
        config = GORGIAS_ENDPOINTS[endpoint]
        advertised = {f["field"] for f in config.incremental_fields}
        # Every advertised cursor field must be one Gorgias actually accepts in order_by.
        assert advertised <= DOCUMENTED_ORDER_BY_DATETIME_FIELDS[endpoint]
        # supports_incremental and the field list must agree.
        assert bool(advertised) == config.supports_incremental

    def test_incremental_endpoints_use_updated_when_available_else_created(self) -> None:
        # Mutable resources must track updates when the API lets them; append-only ones
        # track creation. This guards the core correctness decision per endpoint.
        expected = {
            "tickets": "updated_datetime",
            "customers": "updated_datetime",
            "macros": "updated_datetime",
            "messages": "created_datetime",
            "satisfaction_surveys": "created_datetime",
        }
        actual = {
            name: config.incremental_fields[0]["field"]
            for name, config in GORGIAS_ENDPOINTS.items()
            if config.supports_incremental
        }
        assert actual == expected


class TestGorgiasSource:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = gorgias_source("acme", "e@acme.com", "key", endpoint, MagicMock(), _FakeManager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [GORGIAS_ENDPOINTS[endpoint].partition_key]
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            (name, config.incremental_fields[0]["field"])
            for name, config in GORGIAS_ENDPOINTS.items()
            if config.supports_incremental
        ]
    )
    def test_incremental_source_response_sorts_descending(self, endpoint: str, incremental_field: str) -> None:
        response = gorgias_source(
            "acme",
            "e@acme.com",
            "key",
            endpoint,
            MagicMock(),
            _FakeManager(),
            should_use_incremental_field=True,
            incremental_field=incremental_field,
        )
        assert response.sort_mode == "desc"

    def test_every_endpoint_partitions_on_created_datetime(self) -> None:
        for config in GORGIAS_ENDPOINTS.values():
            assert config.partition_key == "created_datetime"
            assert "updated" not in config.partition_key
