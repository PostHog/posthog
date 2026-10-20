import json
from typing import Any, cast

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.canny.canny import (
    PAGE_SIZE,
    CannyBodyAuth,
    CannyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.settings import (
    CANNY_API_VERSION_V1,
    CANNY_API_VERSION_V2,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.source import CannySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.canny import CannySourceConfig


def _driver(api_key: str = "k") -> SourceDriver:
    return SourceDriver(CannySource(), CannySourceConfig(api_key=api_key))


def _page(key: str, ids: list[str], has_more: bool) -> ScriptedResponse:
    return ScriptedResponse(json={key: [{"id": i} for i in ids], "hasMore": has_more})


def _full_page(key: str, start: int, has_more: bool = True) -> ScriptedResponse:
    return _page(key, [str(i) for i in range(start, start + PAGE_SIZE)], has_more)


def _cursor_page(key: str, ids: list[str], cursor: str | None, has_next: bool) -> ScriptedResponse:
    return ScriptedResponse(json={key: [{"id": i} for i in ids], "cursor": cursor, "hasNextPage": has_next})


class TestCannyBodyAuth:
    def test_injects_api_key_into_existing_json_body(self) -> None:
        request = requests.Request(
            method="POST",
            url="https://canny.io/api/v1/posts/list",
            json={"skip": 0, "limit": PAGE_SIZE},
            auth=CannyBodyAuth("secret"),
        )
        prepared = requests.Session().prepare_request(request)
        assert json.loads(cast("str | bytes", prepared.body)) == {"skip": 0, "limit": PAGE_SIZE, "apiKey": "secret"}

    def test_creates_body_when_absent(self) -> None:
        # boards/list sends no pagination params, so the body is just the key.
        request = requests.Request(
            method="POST", url="https://canny.io/api/v1/boards/list", auth=CannyBodyAuth("secret")
        )
        prepared = requests.Session().prepare_request(request)
        assert json.loads(cast("str | bytes", prepared.body)) == {"apiKey": "secret"}

    def test_declares_api_key_as_secret_for_redaction(self) -> None:
        assert CannyBodyAuth("secret").secret_values() == ("secret",)


class TestPagination:
    def test_paginates_until_has_more_false_and_saves_after_each_page(self) -> None:
        result = _driver().run(
            "posts",
            [_full_page("posts", 0), _full_page("posts", PAGE_SIZE), _page("posts", ["final"], False)],
            api_version=CANNY_API_VERSION_V1,
        )

        assert [row["id"] for row in result.rows] == [*(str(i) for i in range(2 * PAGE_SIZE)), "final"]
        assert [request.json().get("skip") for request in result.requests] == [0, PAGE_SIZE, PAGE_SIZE * 2]
        assert all(request.json().get("limit") == PAGE_SIZE for request in result.requests)
        # State is saved after each non-terminal page so a crash re-yields rather than skips.
        assert result.saved_states == [CannyResumeConfig(skip=PAGE_SIZE), CannyResumeConfig(skip=PAGE_SIZE * 2)]
        assert result.raised is None

    def test_full_page_with_has_more_false_stops_without_extra_request(self) -> None:
        # Termination is driven by Canny's hasMore flag, not page size — a full last page must
        # not trigger a wasted empty-page probe.
        result = _driver().run("posts", [_full_page("posts", 0, has_more=False)], api_version=CANNY_API_VERSION_V1)

        assert len(result.rows) == PAGE_SIZE
        assert len(result.requests) == 1
        assert result.raised is None

    def test_resume_seeds_skip_from_saved_state(self) -> None:
        result = _driver().run(
            "posts",
            [_page("posts", ["x"], False)],
            resume_state=CannyResumeConfig(skip=PAGE_SIZE * 2),
            api_version=CANNY_API_VERSION_V1,
        )

        assert result.requests[0].json().get("skip") == PAGE_SIZE * 2
        assert [row["id"] for row in result.rows] == ["x"]
        assert result.raised is None

    def test_terminal_single_page_does_not_save_state(self) -> None:
        result = _driver().run("posts", [_page("posts", ["only"], False)], api_version=CANNY_API_VERSION_V1)

        assert [row["id"] for row in result.rows] == ["only"]
        assert result.saved_states == []
        assert result.raised is None

    def test_unpaginated_endpoint_fetches_once_without_pagination_params(self) -> None:
        # boards/list has no hasMore flag; a single fetch must terminate the loop.
        result = _driver().run("boards", [ScriptedResponse(json={"boards": [{"id": "b1"}]})])

        assert len(result.requests) == 1
        assert "skip" not in result.requests[0].json()
        assert "limit" not in result.requests[0].json()
        assert result.rows == [{"id": "b1"}]
        assert result.saved_states == []
        assert result.raised is None

    def test_empty_page_yields_nothing(self) -> None:
        result = _driver().run("posts", [_page("posts", [], False)], api_version=CANNY_API_VERSION_V1)

        assert result.rows == []
        assert result.saved_states == []
        assert result.raised is None

    @pytest.mark.parametrize(
        "body",
        [{}, {"posts": None}, {"posts": {"id": "1"}}, {"other": [{"id": "1"}]}],
    )
    def test_missing_or_non_list_data_key_yields_nothing(self, body: dict[str, Any]) -> None:
        result = _driver().run("posts", [ScriptedResponse(json=body)], api_version=CANNY_API_VERSION_V1)

        assert result.rows == []
        assert result.raised is None

    def test_error_body_on_200_raises_http_error(self) -> None:
        # Canny can return 200 with an {"error": ...} body for a bad API key; the message must
        # carry the error text so the friendly non-retryable mapping can match it.
        result = _driver().run("posts", [ScriptedResponse(json={"error": "invalid API key"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "invalid API key" in str(result.raised)

    def test_error_body_on_unpaginated_endpoint_raises(self) -> None:
        result = _driver().run("boards", [ScriptedResponse(json={"error": "invalid API key"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "invalid API key" in str(result.raised)

    def test_registers_api_key_for_redaction(self) -> None:
        # The secret rides in the POST body through the tracked transport; it must be redacted so
        # it never lands in HTTP logs/samples.
        result = _driver("secret").run("posts", [_page("posts", [], False)], api_version=CANNY_API_VERSION_V1)

        assert result.session_options == [{"redact_values": ("secret",)}]
        assert result.raised is None


class TestRetries:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_status_is_retried_then_succeeds(self, status: int) -> None:
        result = _driver().run("posts", [ScriptedResponse(status=status, json={}), _page("posts", ["a"], False)])

        assert [row["id"] for row in result.rows] == ["a"]
        assert len(result.requests) == 2
        assert result.raised is None

    def test_retries_exhaust_then_raise(self) -> None:
        result = _driver().run("posts", always(ScriptedResponse(status=500, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @pytest.mark.parametrize(
        ("status", "reason"),
        [(400, "Bad Request"), (401, "Unauthorized"), (403, "Forbidden")],
    )
    def test_client_errors_raise_http_error_without_retry(self, status: int, reason: str) -> None:
        result = _driver().run("posts", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error" in str(result.raised)
        assert reason in str(result.raised)
        assert len(result.requests) == 1

    def test_unauthorized_message_matches_non_retryable_mapping(self) -> None:
        # source.py maps this exact substring to the friendly invalid-key message.
        result = _driver().run("posts", [ScriptedResponse(status=401, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized for url: https://canny.io" in str(result.raised)


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        with scripted_network([ScriptedResponse(json={"boards": []})]) as network:
            assert validate_credentials("k") is True

        assert network.requests_log[0].path == "/api/v1/boards/list"
        assert network.requests_log[0].body == b"apiKey=k"

    def test_error_body_is_invalid(self) -> None:
        with scripted_network([ScriptedResponse(json={"error": "invalid API key"})]):
            assert validate_credentials("k") is False

    def test_registers_api_key_for_redaction(self) -> None:
        with scripted_network([ScriptedResponse(json={"boards": []})]) as network:
            validate_credentials("secret")

        assert network.session_options == [{"redact_values": ("secret",)}]


class TestCannySource:
    # Opportunities and groups are the only Canny objects the API returns with no timestamp field
    # at all, so partitioning them would key on a column that never arrives.
    UNPARTITIONED_ENDPOINTS = {"groups", "opportunities"}

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={})])
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert result.raised is None

        if endpoint in self.UNPARTITIONED_ENDPOINTS:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["created"]


class TestV2CursorPagination:
    # Canny's v2 wire is cursor-paginated and keys records per endpoint: users and companies keep
    # their named keys, comments uses the generic `items`.
    V2_ENDPOINTS = [("companies", "companies"), ("comments", "items"), ("users", "users")]

    @pytest.mark.parametrize(("endpoint", "data_key"), V2_ENDPOINTS)
    def test_cursor_paginates_reads_v2_key_and_hits_v2_path(self, endpoint: str, data_key: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _cursor_page(data_key, ["a", "b"], cursor="cur-1", has_next=True),
                _cursor_page(data_key, ["c"], cursor=None, has_next=False),
            ],
            api_version=CANNY_API_VERSION_V2,
        )

        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert result.urls == [f"https://canny.io/api/v2/{endpoint}/list"] * 2
        # limit rides every request; the cursor is absent on the first and forwarded on the next.
        assert result.requests[0].json().get("limit") == PAGE_SIZE
        assert "cursor" not in result.requests[0].json()
        assert result.requests[1].json().get("cursor") == "cur-1"
        # The non-terminal page checkpoints its cursor so a crash resumes rather than restarts.
        assert result.saved_states == [CannyResumeConfig(cursor="cur-1")]
        assert result.raised is None

    def test_resume_seeds_cursor_from_saved_state(self) -> None:
        result = _driver().run(
            "companies",
            [_cursor_page("companies", ["x"], cursor=None, has_next=False)],
            resume_state=CannyResumeConfig(cursor="cur-99"),
            api_version=CANNY_API_VERSION_V2,
        )

        assert result.requests[0].json().get("cursor") == "cur-99"
        assert [row["id"] for row in result.rows] == ["x"]
        assert result.raised is None

    def test_error_body_on_v2_raises_http_error(self) -> None:
        result = _driver().run("companies", [ScriptedResponse(json={"error": "invalid API key"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "invalid API key" in str(result.raised)

    def test_v2_pin_keeps_non_v2_endpoint_on_v1_skip_wire(self) -> None:
        # posts has no v2 implementation, so a v2-pinned source must still request the v1 path with
        # skip/limit pagination — never a guessed /v2/posts/list that would 404.
        result = _driver().run("posts", [_page("posts", ["p1"], False)], api_version=CANNY_API_VERSION_V2)

        assert result.urls == ["https://canny.io/api/v1/posts/list"]
        assert result.requests[0].json().get("skip") == 0
        assert result.requests[0].json().get("limit") == PAGE_SIZE
        assert [row["id"] for row in result.rows] == ["p1"]
        assert result.raised is None

    def test_v1_pin_keeps_v2_capable_endpoint_on_v1_wire(self) -> None:
        # A v1-pinned companies source stays byte-for-byte on the v1 skip/limit path and `companies`
        # key, unaffected by the new default.
        result = _driver().run("companies", [_page("companies", ["c1"], False)], api_version=CANNY_API_VERSION_V1)

        assert result.urls == ["https://canny.io/api/v1/companies/list"]
        assert result.requests[0].json().get("skip") == 0
        assert "cursor" not in result.requests[0].json()
        assert [row["id"] for row in result.rows] == ["c1"]
        assert result.raised is None


class TestIdeasEraEndpoints:
    # Canny shipped the Ideas-era endpoints on the v1 base but with the cursor wire, so the
    # pagination style cannot be inferred from the version pin.
    CURSOR_V1_ENDPOINTS = ["groups", "ideas", "insights"]

    @pytest.mark.parametrize("api_version", [CANNY_API_VERSION_V1, CANNY_API_VERSION_V2])
    @pytest.mark.parametrize("endpoint", CURSOR_V1_ENDPOINTS)
    def test_cursor_paginates_on_v1_path_under_either_pin(self, endpoint: str, api_version: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _cursor_page("items", ["a", "b"], cursor="cur-1", has_next=True),
                _cursor_page("items", ["c"], cursor=None, has_next=False),
            ],
            api_version=api_version,
        )

        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        # These have no v2 implementation; a guessed /v2/ path would 404, and skip/limit would
        # silently re-read page one forever.
        assert result.urls == [f"https://canny.io/api/v1/{endpoint}/list"] * 2
        assert "skip" not in result.requests[0].json()
        assert result.requests[0].json().get("limit") == PAGE_SIZE
        assert "cursor" not in result.requests[0].json()
        assert result.requests[1].json().get("cursor") == "cur-1"
        assert result.saved_states == [CannyResumeConfig(cursor="cur-1")]
        assert result.raised is None

    def test_resume_seeds_cursor_under_v1_pin(self) -> None:
        # A v1 pin used to imply offset resume; these endpoints must read the saved cursor instead.
        result = _driver().run(
            "ideas",
            [_cursor_page("items", ["x"], cursor=None, has_next=False)],
            resume_state=CannyResumeConfig(cursor="cur-77"),
            api_version=CANNY_API_VERSION_V1,
        )

        assert result.requests[0].json().get("cursor") == "cur-77"
        assert "skip" not in result.requests[0].json()
        assert [row["id"] for row in result.rows] == ["x"]
        assert result.raised is None

    @pytest.mark.parametrize("api_version", [CANNY_API_VERSION_V1, CANNY_API_VERSION_V2])
    def test_opportunities_stay_on_the_skip_wire(self, api_version: str) -> None:
        # Opportunities is the one Ideas-era endpoint Canny left on skip/limit with `hasMore`.
        result = _driver().run(
            "opportunities",
            [_full_page("opportunities", 0), _page("opportunities", ["final"], False)],
            api_version=api_version,
        )

        assert [row["id"] for row in result.rows] == [*(str(i) for i in range(PAGE_SIZE)), "final"]
        assert result.urls == ["https://canny.io/api/v1/opportunities/list"] * 2
        assert [request.json().get("skip") for request in result.requests] == [0, PAGE_SIZE]
        assert "cursor" not in result.requests[0].json()
        assert result.saved_states == [CannyResumeConfig(skip=PAGE_SIZE)]
        assert result.raised is None
