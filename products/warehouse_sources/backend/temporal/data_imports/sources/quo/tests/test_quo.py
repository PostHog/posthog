from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.quo import QuoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.quo import (
    QuoResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.settings import (
    QUO_API_VERSION_2026_03_30,
    QUO_API_VERSION_V1,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.quo.source import QuoSource

WATERMARK = datetime(2026, 1, 1, tzinfo=UTC)
WATERMARK_ISO = "2026-01-01T00:00:00+00:00"


def _page(items: list[dict[str, Any]], next_page_token: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items}
    if next_page_token is not None:
        body["nextPageToken"] = next_page_token
    return ScriptedResponse(json=body)


def _dated_page(items: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "nextCursor": next_cursor})


def _source(endpoint: str, script: Script, api_version: str = QUO_API_VERSION_V1, **inputs: Any) -> DriveResult:
    return SourceDriver(QuoSource(), QuoSourceConfig(api_key="key")).run(
        endpoint, script, api_version=api_version, **inputs
    )


def _ids(result: DriveResult) -> list[str]:
    return [row["id"] for row in result.rows]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "api_version, expected_url, expected_version_header",
        [
            (QUO_API_VERSION_V1, "https://api.quo.com/v1/phone-numbers", None),
            (QUO_API_VERSION_2026_03_30, "https://api.quo.com/phone-numbers", "2026-03-30"),
        ],
    )
    def test_validate_credentials_probes_phone_numbers_with_raw_key(
        self, api_version, expected_url, expected_version_header
    ):
        with scripted_network([ScriptedResponse(json={"data": []})]) as network:
            assert validate_credentials("key", api_version) is True

        request = network.requests_log[0]
        assert request.url == expected_url
        # Quo takes the raw key in the Authorization header, with no Bearer prefix.
        assert request.headers["authorization"] == "key"
        assert request.headers.get("quo-api-version") == expected_version_header


class TestTopLevelPagination:
    def test_paginates_via_page_token(self):
        result = _source(
            "users",
            [
                _page([{"id": "US1"}, {"id": "US2"}], next_page_token="tok"),
                _page([{"id": "US3"}]),
            ],
        )

        assert _ids(result) == ["US1", "US2", "US3"]
        assert result.queries[0] == {"maxResults": ("50",)}
        assert result.queries[1] == {"maxResults": ("50",), "pageToken": ("tok",)}
        # State is saved only while a next page exists.
        assert result.saved_states == [QuoResumeConfig(page_token="tok")]

    def test_resumes_from_saved_state(self):
        result = _source("users", [_page([{"id": "US9"}])], resume_state=QuoResumeConfig(page_token="tok5"))

        assert _ids(result) == ["US9"]
        assert result.params("pageToken") == ["tok5"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self):
        result = _source("users", [_page([{"id": "US9"}])])

        assert result.params("pageToken") == [None]

    def test_ignores_state_saved_under_a_dated_version(self):
        result = _source(
            "users",
            [_page([{"id": "US9"}])],
            resume_state=QuoResumeConfig(page_token="cur5", api_version="2026-03-30"),
        )

        assert result.params("pageToken") == [None]

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [
            ("createdAt", "createdAfter"),
            ("updatedAt", "updatedAfter"),
        ],
    )
    def test_incremental_run_maps_cursor_field_to_server_filter(self, incremental_field, expected_param):
        result = _source(
            "conversations",
            [_page([{"id": "CN1"}])],
            db_incremental_field_last_value=WATERMARK,
            incremental_field=incremental_field,
        )

        assert result.queries == [{"maxResults": ("100",), expected_param: (WATERMARK_ISO,)}]


class TestFanOut:
    @pytest.mark.parametrize(
        "endpoint, expected_group_queried",
        [
            # /v1/calls serves one-to-one conversations only; /v1/messages accepts the group's
            # full participants array.
            ("calls", False),
            ("messages", True),
        ],
    )
    def test_group_conversations_skipped_for_calls_only(self, endpoint, expected_group_queried):
        group_conversation = {"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001", "+15550002"]}
        one_to_one = {"id": "CN2", "phoneNumberId": "PN1", "participants": ["+15550003"]}
        child_pages = [_page([{"id": "A1"}])]
        if expected_group_queried:
            child_pages.append(_page([{"id": "A2"}]))

        result = _source(endpoint, [_page([group_conversation, one_to_one]), *child_pages])

        participants_queried = [list(request.query["participants"]) for request in result.requests[1:]]
        if expected_group_queried:
            assert participants_queried == [["+15550001", "+15550002"], ["+15550003"]]
        else:
            assert participants_queried == [["+15550003"]]

    def test_duplicate_and_incomplete_conversations_produce_no_extra_requests(self):
        result = _source(
            "messages",
            [
                _page(
                    [
                        {"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001"]},
                        # Same pair again (e.g. a deleted and recreated conversation).
                        {"id": "CN2", "phoneNumberId": "PN1", "participants": ["+15550001"]},
                        {"id": "CN3", "phoneNumberId": None, "participants": ["+15550002"]},
                        {"id": "CN4", "phoneNumberId": "PN1", "participants": []},
                    ]
                ),
                _page([{"id": "AM1"}]),
            ],
        )

        assert _ids(result) == ["AM1"]
        assert len(result.requests) == 2

    def test_child_pagination_follows_page_token(self):
        result = _source(
            "calls",
            [
                _page([{"id": "CN1", "phoneNumberId": "PN1", "participants": ["+15550001"]}]),
                _page([{"id": "AC1"}], next_page_token="tok"),
                _page([{"id": "AC2"}]),
            ],
        )

        assert _ids(result) == ["AC1", "AC2"]
        assert result.requests[2].param("pageToken") == "tok"


class TestDatedVersion:
    def test_paginates_via_after_cursor_with_version_header(self):
        result = _source(
            "users",
            [
                _dated_page([{"id": "US1"}, {"id": "US2"}], next_cursor="cur"),
                _dated_page([{"id": "US3"}]),
            ],
            api_version=QUO_API_VERSION_2026_03_30,
        )

        assert _ids(result) == ["US1", "US2", "US3"]
        assert result.urls[0] == "https://api.quo.com/users?limit=50"
        assert result.queries[0] == {"limit": ("50",)}
        assert result.queries[1] == {"limit": ("50",), "after": ("cur",)}
        assert result.requests[0].headers["quo-api-version"] == "2026-03-30"
        assert result.saved_states == [QuoResumeConfig(page_token="cur", api_version="2026-03-30")]

    @pytest.mark.parametrize(
        "resume_state, expected_after",
        [
            (QuoResumeConfig(page_token="cur5", api_version="2026-03-30"), "cur5"),
            # A v1 pageToken means nothing to the dated `after` param.
            (QuoResumeConfig(page_token="tok5"), None),
        ],
    )
    def test_resumes_only_from_state_saved_on_the_same_wire(self, resume_state, expected_after):
        result = _source(
            "users",
            [_dated_page([{"id": "US9"}])],
            api_version=QUO_API_VERSION_2026_03_30,
            resume_state=resume_state,
        )

        assert result.params("after") == [expected_after]

    @pytest.mark.parametrize(
        "endpoint, incremental_field, expected_params",
        [
            ("conversations", "createdAt", {"limit": "50", "createdAt[gte]": WATERMARK_ISO}),
            ("conversations", "updatedAt", {"limit": "50", "updatedAt[gte]": WATERMARK_ISO}),
            ("calls", "createdAt", {"limit": "50", "include": "summary", "createdAt[gte]": WATERMARK_ISO}),
            ("messages", "createdAt", {"limit": "50", "createdAt[gt]": WATERMARK_ISO}),
        ],
    )
    def test_incremental_run_uses_range_filters_without_fan_out(self, endpoint, incremental_field, expected_params):
        result = _source(
            endpoint,
            [_dated_page([{"id": "X1"}])],
            api_version=QUO_API_VERSION_2026_03_30,
            db_incremental_field_last_value=WATERMARK,
            incremental_field=incremental_field,
        )

        assert _ids(result) == ["X1"]
        assert result.paths == [f"/{endpoint}"]
        assert result.urls[0].startswith(f"https://api.quo.com/{endpoint}?")
        assert {name: values[0] for name, values in result.queries[0].items()} == expected_params

    def test_phone_numbers_request_restrictions(self):
        result = _source("phone_numbers", [_dated_page([{"id": "PN1"}])], api_version=QUO_API_VERSION_2026_03_30)

        assert result.paths == ["/phone-numbers"]
        assert result.queries[0] == {"limit": ("50",), "include": ("restrictions",)}

    def test_contact_custom_fields_stay_on_v1_wire(self):
        result = _source("contact_custom_fields", [_page([{"key": "k1"}])], api_version=QUO_API_VERSION_2026_03_30)

        assert [row["key"] for row in result.rows] == ["k1"]
        assert result.paths == ["/v1/contact-custom-fields"]
        assert "quo-api-version" not in result.requests[0].headers

    def test_unknown_version_raises(self):
        result = _source("users", [], api_version="2099-01-01")

        assert isinstance(result.raised, ValueError)
        assert "Unsupported Quo API version" in str(result.raised)
        assert result.requests == []


def _notes_state(contacts_cursor: str, contact_id: str, notes_cursor: str | None) -> QuoResumeConfig:
    return QuoResumeConfig(
        page_token=contacts_cursor, api_version="2026-03-30", contact_id=contact_id, notes_cursor=notes_cursor
    )


class TestContactNotes:
    @pytest.mark.parametrize("api_version", [QUO_API_VERSION_V1, QUO_API_VERSION_2026_03_30])
    def test_fans_out_over_contacts_on_the_dated_wire(self, api_version):
        result = _source(
            "contact_notes",
            [
                _dated_page([{"id": "CT1"}, {"id": "CT2"}], next_cursor="c2"),
                _dated_page([{"id": "N1"}], next_cursor="n2"),
                _dated_page([{"id": "N2"}]),
                _dated_page([]),
                _dated_page([{"id": "CT3"}]),
                # CT3 was deleted after the contacts page was read.
                ScriptedResponse(status=404, json={"message": "Not Found"}),
            ],
            api_version=api_version,
        )

        assert result.raised is None
        assert [(row["contactId"], row["id"]) for row in result.rows] == [("CT1", "N1"), ("CT1", "N2")]
        assert result.paths == [
            "/contacts",
            "/contacts/CT1/notes",
            "/contacts/CT1/notes",
            "/contacts/CT2/notes",
            "/contacts",
            "/contacts/CT3/notes",
        ]
        assert result.params("after") == [None, None, "n2", None, "c2", None]
        assert {request.headers["quo-api-version"] for request in result.requests} == {"2026-03-30"}
        assert result.saved_states == [_notes_state("", "CT1", "n2"), _notes_state("", "CT1", None)]

    @pytest.mark.parametrize(
        "resume_state, expected_paths, expected_after",
        [
            (
                _notes_state("c5", "CT2", "n3"),
                ["/contacts", "/contacts/CT2/notes", "/contacts/CT3/notes"],
                ["c5", "n3", None],
            ),
            (
                _notes_state("c5", "CT1", None),
                ["/contacts", "/contacts/CT2/notes", "/contacts/CT3/notes"],
                ["c5", None, None],
            ),
            (
                _notes_state("c5", "CT0", None),
                ["/contacts", "/contacts/CT1/notes", "/contacts/CT2/notes", "/contacts/CT3/notes"],
                ["c5", None, None, None],
            ),
            (
                QuoResumeConfig(page_token="tok5"),
                ["/contacts", "/contacts/CT1/notes", "/contacts/CT2/notes", "/contacts/CT3/notes"],
                [None, None, None, None],
            ),
        ],
    )
    def test_resumes_after_the_last_written_notes_page(self, resume_state, expected_paths, expected_after):
        result = _source(
            "contact_notes",
            [_dated_page([{"id": "CT1"}, {"id": "CT2"}, {"id": "CT3"}]), *[_dated_page([]) for _ in range(3)]],
            resume_state=resume_state,
        )

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.params("after") == expected_after
