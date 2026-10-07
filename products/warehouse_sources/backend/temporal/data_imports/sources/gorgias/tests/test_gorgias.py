import base64
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

import requests
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

    def __init__(self, resume_cursor: str | None = None, resume_variant: int = 0) -> None:
        self._resume_cursor = resume_cursor
        self._resume_variant = resume_variant
        self.saved: list[GorgiasResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_cursor is not None

    def load_state(self) -> GorgiasResumeConfig | None:
        if not self._resume_cursor:
            return None
        return GorgiasResumeConfig(cursor=self._resume_cursor, variant=self._resume_variant)

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

    def test_stages_next_position_before_yielding_each_batch(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": "c2"}}),
            _response(json_body={"data": [{"id": 2}], "meta": {"next_cursor": None}}),
        ]
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            rows = get_rows("acme", "e@acme.com", "key", "tickets", MagicMock(), manager)
            assert next(rows) == [{"id": 1}]
            assert manager.saved[-1] == GorgiasResumeConfig(cursor="c2", variant=0)
            assert next(rows) == [{"id": 2}]
            # The last page stages a position past the only variant, so a resume reads nothing.
            assert manager.saved[-1] == GorgiasResumeConfig(cursor=None, variant=1)
            assert list(rows) == []

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


class TestParamVariants:
    def test_custom_fields_paginates_each_object_type_from_a_fresh_cursor(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": "t2"}}),
            _response(json_body={"data": [{"id": 2}], "meta": {"next_cursor": None}}),
            _response(json_body={"data": [{"id": 3}], "meta": {"next_cursor": None}}),
        ]
        manager = _FakeManager()
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("acme", "e@acme.com", "key", "custom_fields", MagicMock(), manager))

        assert batches == [[{"id": 1}], [{"id": 2}], [{"id": 3}]]
        params = [c.kwargs["params"] for c in session.get.call_args_list]
        assert [(p["object_type"], p.get("cursor")) for p in params] == [
            ("Ticket", None),
            ("Ticket", "t2"),
            ("Customer", None),
        ]
        assert all(p["order_by"] == "priority:asc" for p in params)
        assert [(c.variant, c.cursor) for c in manager.saved] == [(0, "t2"), (1, None), (2, None)]

    def test_resumes_into_saved_variant(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        manager = _FakeManager(resume_cursor="c9", resume_variant=1)
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", "custom_fields", MagicMock(), manager))

        assert session.get.call_count == 1
        params = session.get.call_args.kwargs["params"]
        assert params["object_type"] == "Customer"
        assert params["cursor"] == "c9"

    @parameterized.expand(
        [
            ("voice_calls", "phone/voice-calls"),
            ("voice_call_events", "phone/voice-call-events"),
            ("voice_call_recordings", "phone/voice-call-recordings"),
        ]
    )
    def test_voice_endpoints_send_no_order_by(self, endpoint: str, path: str) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("acme", "e@acme.com", "key", endpoint, MagicMock(), _FakeManager()))

        url = session.get.call_args.args[0]
        assert url == f"https://acme.gorgias.com/api/{path}"
        assert "order_by" not in session.get.call_args.kwargs["params"]


class TestTicketChildTables:
    def _rows(self, endpoint: str, tickets: list[dict]) -> list[dict]:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": tickets, "meta": {"next_cursor": None}})
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("acme", "e@acme.com", "key", endpoint, MagicMock(), _FakeManager()))
        assert session.get.call_args.args[0] == "https://acme.gorgias.com/api/tickets"
        return [row for batch in batches for row in batch]

    def test_ticket_tags_flattens_one_row_per_tag(self) -> None:
        rows = self._rows(
            "ticket_tags",
            [
                {
                    "id": 10,
                    "created_datetime": "2024-01-01T00:00:00+00:00",
                    "tags": [{"id": 1, "name": "urgent"}, {"name": "no-id"}],
                },
                {"id": 11, "created_datetime": "2024-02-01T00:00:00+00:00", "tags": []},
            ],
        )

        assert rows == [
            {"id": 1, "name": "urgent", "ticket_id": 10, "ticket_created_datetime": "2024-01-01T00:00:00+00:00"}
        ]

    def test_ticket_field_values_keys_by_field_and_keeps_value_one_type(self) -> None:
        rows = self._rows(
            "ticket_field_values",
            [
                {
                    "id": 10,
                    "created_datetime": "2024-01-01T00:00:00+00:00",
                    "custom_fields": {
                        "5": {"id": 5, "value": "Order::Status", "prediction": None},
                        "6": {"id": 6, "value": 3},
                        "7": {"id": 7, "value": True},
                        "8": {"id": 8, "value": None},
                    },
                },
                {"id": 11, "created_datetime": "2024-02-01T00:00:00+00:00", "custom_fields": None},
            ],
        )

        assert [(r["ticket_id"], r["field_id"], r["value"]) for r in rows] == [
            (10, 5, "Order::Status"),
            (10, 6, "3"),
            (10, 7, "true"),
            (10, 8, None),
        ]
        assert all(r["ticket_created_datetime"] == "2024-01-01T00:00:00+00:00" for r in rows)


class TestCustomerFieldValues:
    def test_fans_out_per_customer_and_skips_deleted_customers(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_body={
                    "data": [
                        {"id": 1, "created_datetime": "2024-01-01T00:00:00"},
                        {"id": 2, "created_datetime": "2024-02-01T00:00:00"},
                        {"id": 3, "created_datetime": "2024-03-01T00:00:00"},
                    ],
                    "meta": {"next_cursor": None},
                }
            ),
            _response(
                json_body={
                    "data": [
                        {"field": {"id": 5, "label": "Plan"}, "value": "pro"},
                        {"field": {"id": 6, "label": "Seats"}, "value": 12},
                    ]
                }
            ),
            _response(status_code=404, ok=False),
            # Some list endpoints return a bare array rather than a `data` envelope.
            _response(json_body=[{"field": {"id": 5, "label": "Plan"}, "value": None}]),  # type: ignore[arg-type]
        ]
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("acme", "e@acme.com", "key", "customer_field_values", MagicMock(), _FakeManager()))

        urls = [c.args[0] for c in session.get.call_args_list]
        assert urls == [
            "https://acme.gorgias.com/api/customers",
            "https://acme.gorgias.com/api/customers/1/custom-fields",
            "https://acme.gorgias.com/api/customers/2/custom-fields",
            "https://acme.gorgias.com/api/customers/3/custom-fields",
        ]
        rows = [row for batch in batches for row in batch]
        assert [(r["customer_id"], r["field_id"], r["value"], r["customer_created_datetime"]) for r in rows] == [
            (1, 5, "pro", "2024-01-01T00:00:00"),
            (1, 6, "12", "2024-01-01T00:00:00"),
            (3, 5, None, "2024-03-01T00:00:00"),
        ]

    def test_child_error_other_than_404_fails_the_sync(self) -> None:
        session = MagicMock()
        forbidden = _response(status_code=403, ok=False)
        forbidden.raise_for_status.side_effect = requests.HTTPError(
            "403 Client Error: Forbidden for url", response=forbidden
        )
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": None}}),
            forbidden,
        ]
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("acme", "e@acme.com", "key", "customer_field_values", MagicMock(), _FakeManager()))

    def test_stages_parent_cursor_and_reaches_safe_point_on_pages_without_values(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_body={"data": [{"id": 1}], "meta": {"next_cursor": "c2"}}),
            _response(json_body={"data": []}),
            _response(json_body={"data": [{"id": 2}], "meta": {"next_cursor": None}}),
            _response(json_body={"data": [{"field": {"id": 5}, "value": "x"}]}),
        ]
        manager = _FakeManager()
        with (
            patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session),
            patch.object(manager, "safe_point") as safe_point,
        ):
            rows = get_rows("acme", "e@acme.com", "key", "customer_field_values", MagicMock(), manager)
            assert [r["customer_id"] for r in next(rows)] == [2]
            assert manager.saved == [
                GorgiasResumeConfig(cursor="c2", variant=0),
                GorgiasResumeConfig(cursor=None, variant=1),
            ]
            safe_point.assert_called_once()
            assert list(rows) == []


class TestServerFilteredIncremental:
    def _run(self, session: MagicMock, watermark: datetime | None) -> list:
        with patch(f"{GORGIAS_MODULE}.make_tracked_session", return_value=session):
            return list(
                get_rows(
                    "acme",
                    "e@acme.com",
                    "key",
                    "events",
                    MagicMock(),
                    _FakeManager(),
                    should_use_incremental_field=True,
                    incremental_field="created_datetime",
                    db_incremental_field_last_value=watermark,
                )
            )

    def test_filters_from_watermark_ascending_on_every_page(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_body={
                    "data": [{"id": 1, "created_datetime": "2023-06-01T00:00:00"}],
                    "meta": {"next_cursor": "c2"},
                }
            ),
            _response(
                json_body={
                    "data": [{"id": 2, "created_datetime": "2023-06-02T00:00:00"}],
                    "meta": {"next_cursor": None},
                }
            ),
        ]
        batches = self._run(session, datetime(2023, 6, 1, tzinfo=UTC))

        assert [item["id"] for batch in batches for item in batch] == [1, 2]
        params = [c.kwargs["params"] for c in session.get.call_args_list]
        assert [(p["order_by"], p["created_datetime[gte]"], p.get("cursor")) for p in params] == [
            ("created_datetime:asc", "2023-06-01T00:00:00+00:00", None),
            ("created_datetime:asc", "2023-06-01T00:00:00+00:00", "c2"),
        ]

    def test_first_sync_sends_no_filter(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(json_body={"data": [], "meta": {"next_cursor": None}})
        self._run(session, None)

        params = session.get.call_args.kwargs["params"]
        assert params["order_by"] == "created_datetime:asc"
        assert "created_datetime[gte]" not in params

    def test_source_response_sorts_ascending(self) -> None:
        response = gorgias_source(
            "acme",
            "e@acme.com",
            "key",
            "events",
            MagicMock(),
            _FakeManager(),
            should_use_incremental_field=True,
            incremental_field="created_datetime",
        )
        assert response.sort_mode == "asc"


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
    "custom_fields": set(),  # only priority:asc/desc
    "voice_calls": set(),  # accepts no order_by
    "ticket_tags": {"created_datetime", "updated_datetime"},
    "ticket_field_values": {"created_datetime", "updated_datetime"},
    "events": {"created_datetime"},
    "voice_call_events": set(),  # accepts no order_by
    "voice_call_recordings": set(),  # accepts no order_by
    "customer_field_values": {"created_datetime", "updated_datetime"},
}
DOCUMENTED_NON_DATETIME_ORDER_BY: dict[str, set[str]] = {
    "custom_fields": {"priority:asc", "priority:desc"},
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
        accepted = {
            f"{field}:{direction}"
            for field in DOCUMENTED_ORDER_BY_DATETIME_FIELDS[endpoint]
            for direction in ("asc", "desc")
        } | DOCUMENTED_NON_DATETIME_ORDER_BY.get(endpoint, set())
        if accepted:
            assert config.order_by in accepted
        else:
            assert config.order_by is None

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
            "events": "created_datetime",
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
        assert response.primary_keys == list(GORGIAS_ENDPOINTS[endpoint].primary_keys)
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [GORGIAS_ENDPOINTS[endpoint].partition_key]
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            (name, config.incremental_fields[0]["field"])
            for name, config in GORGIAS_ENDPOINTS.items()
            if config.supports_incremental and not config.filterable_datetime_fields
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
            assert config.partition_key in ("created_datetime", "ticket_created_datetime", "customer_created_datetime")
            assert "updated" not in config.partition_key
