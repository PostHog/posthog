from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.reply_io._config import ReplyIoSourceConfig
from products.warehouse_sources.sources.reply_io.reply_io import (
    ReplyIoResumeConfig,
    check_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.sources.reply_io.settings import ENDPOINTS, PAGE_SIZE, REPLY_IO_ENDPOINTS
from products.warehouse_sources.sources.reply_io.source import ReplyIoSource
from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)


def _driver() -> SourceDriver:
    return SourceDriver(ReplyIoSource(), ReplyIoSourceConfig(api_key="reply-key"))


def _paged(items: list[dict[str, Any]], has_more: bool) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items, "hasMore": has_more})


def _bare(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestPagination:
    def test_follows_offset_pagination_until_hasmore_false(self) -> None:
        # A short page (< PAGE_SIZE) with hasMore=True must continue — Reply's hasMore is
        # authoritative, so unlike the built-in OffsetPaginator we don't stop on a short page.
        result = _driver().run(
            "contacts",
            [_paged([{"id": 1}, {"id": 2}, {"id": 3}], has_more=True), _paged([{"id": 4}, {"id": 5}], has_more=False)],
        )

        assert [r["id"] for r in result.rows] == [1, 2, 3, 4, 5]
        assert dict(result.requests[0].query) == {"top": (str(PAGE_SIZE),), "skip": ("0",)}
        # Offset advances by rows RECEIVED (3), not PAGE_SIZE — robust to a server-side page cap.
        assert result.requests[1].param("skip") == "3"
        # Checkpoint saved once after the first page (points at the next page); hasMore=false ends it.
        assert result.saved_states == [ReplyIoResumeConfig(skip=3)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "contacts",
            [_paged([{"id": 201}], has_more=False)],
            resume_state=ReplyIoResumeConfig(skip=200),
        )

        assert [r["id"] for r in result.rows] == [201]
        # The initial (skip=0) page is never fetched on resume.
        assert result.params("skip") == ["200"]

    @parameterized.expand(
        [("custom_fields",), ("email_template_folders",), ("linkedin_accounts",), ("sequence_folders",)]
    )
    def test_unpaginated_endpoint_fetches_bare_array_once_without_state(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_bare([{"id": 1}, {"id": 2}])])

        assert [r["id"] for r in result.rows] == [1, 2]
        assert len(result.requests) == 1
        # Bare-array endpoints take no pagination params and never persist resume state.
        assert "top" not in result.requests[0].query and "skip" not in result.requests[0].query
        assert result.saved_states == []

    def test_malformed_body_exhausts_retries_and_raises_retryable(self) -> None:
        result = _driver().run("contacts", always(_bare([{"id": 1}])))

        assert isinstance(result.raised, RESTClientRetryableError)

    @parameterized.expand(
        [
            (
                "email_activity",
                "/v3/reporting/emails",
                {"contactId": 1, "emailAccountId": 9, "deliveryDate": "2026-01-01T10:00:00Z"},
                {"contactId": 2, "emailAccountId": 9, "deliveryDate": "2026-01-02T10:00:00Z"},
            ),
            (
                "meetings",
                "/v3/reporting/team-performance/meetings",
                {"userId": 1, "source": "call", "contactFullName": "Ada Example", "bookedAt": "2026-01-01T10:00:00"},
                {"userId": 2, "source": "linkedIn", "contactFullName": "Bo Example", "bookedAt": "2026-01-02T10:00:00"},
            ),
        ]
    )
    def test_report_posts_all_time_filters_on_every_page(
        self, endpoint: str, path: str, first_row: dict[str, Any], second_row: dict[str, Any]
    ) -> None:
        result = _driver().run(endpoint, [_paged([first_row], has_more=True), _paged([second_row], has_more=False)])

        assert result.rows == [first_row, second_row]
        assert [(r.method, r.path) for r in result.requests] == [("POST", path), ("POST", path)]
        assert result.params("skip") == ["0", "1"]
        # Without a window the report returns only the last seven days.
        expected_body = {"filters": {"dateRangePreset": "allTime", "includeOutOfSequence": True}}
        assert [r.json() for r in result.requests] == [expected_body, expected_body]

    def test_sequence_contacts_pages_each_sequence_in_adding_order(self) -> None:
        result = _driver().run(
            "sequence_contacts",
            route(
                {
                    "/sequences": [_paged([{"id": 7}, {"id": 8}], has_more=False)],
                    "/sequences/7/contacts": [
                        _paged([{"sequenceId": 7, "contactId": 1}], has_more=True),
                        _paged([{"sequenceId": 7, "contactId": 2}], has_more=False),
                    ],
                    "/sequences/8/contacts": [_paged([{"sequenceId": 8, "contactId": 1}], has_more=False)],
                }
            ),
        )

        assert [(r["sequenceId"], r["contactId"]) for r in result.rows] == [(7, 1), (7, 2), (8, 1)]
        child_requests = [r for r in result.requests if r.path.endswith("/contacts")]
        assert [(r.path, r.param("skip")) for r in child_requests] == [
            ("/v3/sequences/7/contacts", "0"),
            ("/v3/sequences/7/contacts", "1"),
            ("/v3/sequences/8/contacts", "0"),
        ]
        assert all(r.param("sort_by") == "addingDate" and r.param("sort_direction") == "asc" for r in child_requests)

    def test_sequence_steps_carry_sequence_id_and_skip_deleted_sequences(self) -> None:
        result = _driver().run(
            "sequence_steps",
            route(
                {
                    "/sequences": [_paged([{"id": 7}, {"id": 8}], has_more=False)],
                    "/sequences/7/steps": [_bare([{"id": 50, "type": "email"}, {"id": 51, "type": "call"}])],
                    # A sequence deleted between the listing and its step fetch.
                    "/sequences/8/steps": [ScriptedResponse(status=404, json={})],
                }
            ),
        )

        assert result.raised is None
        assert [(r["sequenceId"], r["id"]) for r in result.rows] == [(7, 50), (7, 51)]
        assert all("_sequences_id" not in r for r in result.rows)

    def test_sequence_folder_sequences_page_each_folder_and_carry_folder_id(self) -> None:
        result = _driver().run(
            "sequence_folder_sequences",
            route(
                {
                    "/sequence-folders": [
                        _bare([{"id": "folder-a", "name": "Sales"}, {"id": "folder-b", "name": "Old"}])
                    ],
                    "/sequence-folders/folder-a/sequences": [
                        _paged([{"id": 7, "name": "Intro"}], has_more=True),
                        _paged([{"id": 8, "name": "Follow up"}], has_more=False),
                    ],
                    # A folder deleted between the listing and its sequence fetch.
                    "/sequence-folders/folder-b/sequences": [ScriptedResponse(status=404, json={})],
                }
            ),
        )

        assert result.raised is None
        assert [(r["folderId"], r["id"]) for r in result.rows] == [("folder-a", 7), ("folder-a", 8)]
        assert all("_sequence_folders_id" not in r for r in result.rows)
        child_requests = [r for r in result.requests if r.path.endswith("/sequences")]
        assert [(r.path, r.param("skip")) for r in child_requests] == [
            ("/v3/sequence-folders/folder-a/sequences", "0"),
            ("/v3/sequence-folders/folder-a/sequences", "1"),
            ("/v3/sequence-folders/folder-b/sequences", "0"),
        ]

    def test_fanout_resumes_after_finished_sequences(self) -> None:
        script = {
            "/sequences": [_paged([{"id": 7}, {"id": 8}], has_more=False)],
            "/sequences/7/steps": [_bare([{"id": 50}])],
            "/sequences/8/steps": [_bare([{"id": 60}])],
        }
        first = _driver().run("sequence_steps", route(script))
        checkpoint = first.saved_states[0]
        assert checkpoint.fanout_state is not None

        resumed = _driver().run("sequence_steps", route(script), resume_state=checkpoint)

        assert [r["id"] for r in resumed.rows] == [60]
        assert "/v3/sequences/7/steps" not in resumed.paths

    def test_unpaginated_non_array_body_is_retryable(self) -> None:
        result = _driver().run("custom_fields", always(_bare({"items": []})))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Reply API key"),
            ("forbidden", 403, False, "Invalid Reply API key"),
            ("server_error", 500, False, "Reply returned HTTP 500"),
        ]
    )
    def test_validate_credentials_at_source_create(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("reply-key") == (expected_valid, expected_message)

    @parameterized.expand(
        [
            ("sequences", "GET", "/v3/sequences", "Your Reply API key is missing the `sequences:read` scope"),
            # Per-sequence endpoints probe the sequence listing, which needs the same scope.
            ("sequence_steps", "GET", "/v3/sequences", "Your Reply API key is missing the `sequences:read` scope"),
            (
                "email_activity",
                "POST",
                "/v3/reporting/emails",
                "Your Reply API key is missing the `reporting:read` scope",
            ),
            (
                "team_users",
                "GET",
                "/v3/whoami/team-users",
                "Reply only lists team users for accounts that belong to an organization",
            ),
        ]
    )
    def test_validate_credentials_for_endpoint_reports_denied_access(
        self, endpoint: str, method: str, path: str, expected_message: str
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=403, json={}))) as network:
            valid, message = validate_credentials("reply-key", endpoint=endpoint)
        assert (valid, message) == (False, expected_message)
        assert [(r.method, r.path) for r in network.requests_log] == [(method, path)]


class TestEndpointPermissions:
    @parameterized.expand(
        [
            ("throttled", always(ScriptedResponse(status=429, json={}))),
            ("server_error", always(ScriptedResponse(status=500, json={}))),
            ("connection_error", always(requests.ConnectionError("boom"))),
        ]
    )
    def test_transient_errors_do_not_block_the_picker(self, _name: str, script: Script) -> None:
        with scripted_network(script):
            results = check_endpoint_permissions("reply-key", ["contacts"])
        assert results == {"contacts": None}

    def test_unknown_endpoint_reported_reachable_without_probe(self) -> None:
        with scripted_network([]) as network:
            results = check_endpoint_permissions("reply-key", ["not_a_table"])
        assert results == {"not_a_table": None}
        assert network.requests_log == []


class TestReplyIoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = REPLY_IO_ENDPOINTS[endpoint]
        first_request = REPLY_IO_ENDPOINTS[config.fanout.parent_name] if config.fanout else config
        empty = _paged([], has_more=False) if first_request.paginated else _bare([])
        result = _driver().run(endpoint, [empty])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        # Most Reply resources expose no stable creation timestamp, so we don't partition.
        assert result.response.partition_mode is None
