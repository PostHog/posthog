import json
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.octolens import (
    OCTOLENS_BASE_URL,
    PAGE_SIZE,
    OctolensResumeConfig,
    _resource,
    check_access,
    octolens_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.settings import (
    ENDPOINTS,
    OCTOLENS_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the octolens module.
OCTOLENS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.octolens.octolens.make_tracked_session"
)


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _mentions_page(items: list[dict[str, Any]], next_cursor: Optional[str] = None) -> Response:
    return _response({"data": items, "pagination": {"nextCursor": next_cursor}})


def _make_manager(resume_state: OctolensResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request AT SEND TIME.

    ``request.json`` is one dict mutated in place across pages, so inspecting it afterwards shows
    only the final state — copy it when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(
            {
                "url": request.url,
                "method": request.method,
                "json": dict(request.json or {}),
                "params": dict(request.params or {}),
                "auth": request.auth,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in cast(Iterable[Any], source_response.items()) for row in page]


def _source(
    endpoint: str = "mentions",
    manager: Optional[mock.MagicMock] = None,
    *,
    api_key: str = "dummy-key",
    api_version: str = "v2",
):
    return octolens_source(
        api_key=api_key,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        api_version=api_version,
        resumable_source_manager=manager if manager is not None else _make_manager(),
    )


class TestMentionsPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_rides_in_the_post_body_until_exhausted(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _mentions_page([{"sourceId": "reddit_1"}], next_cursor="c1"),
                _mentions_page([{"sourceId": "reddit_2"}], next_cursor=None),
            ],
        )

        rows = _rows(_source("mentions"))

        assert rows == [{"sourceId": "reddit_1"}, {"sourceId": "reddit_2"}]
        assert snapshots[0]["method"] == "POST"
        assert snapshots[0]["url"] == f"{OCTOLENS_BASE_URL}/api/v2/mentions"
        assert "cursor" not in snapshots[0]["json"]
        assert snapshots[1]["json"]["cursor"] == "c1"
        # The cursor must not leak into the query string — the API only reads it from the body.
        assert snapshots[1]["params"] == {}
        assert snapshots[0]["json"]["limit"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_include_all_opts_into_low_relevance_mentions(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_mentions_page([])])

        _rows(_source("mentions"))

        assert snapshots[0]["json"]["includeAll"] is True

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_authenticates_the_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_mentions_page([])])

        _rows(_source("mentions", api_key="secret-key"))

        request = requests.Request(method="POST", url="https://example.com").prepare()
        snapshots[0]["auth"](request)
        assert request.headers["Authorization"] == "Bearer secret-key"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_version_selects_the_url_path_segment(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_mentions_page([])])

        _rows(_source("mentions", api_version="v3"))

        assert snapshots[0]["url"] == f"{OCTOLENS_BASE_URL}/api/v3/mentions"


class TestMentionsFullRefresh:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_never_sends_a_date_filter(self, MockSession) -> None:
        """`filters.startDate` filters on post time, which is not an update-aware cursor.

        Mention rows mutate after they are posted (`sentiment` fills in once scoring finishes,
        `engaged`/`feedbackRelevant` change as people act on them) and Octolens backfills historical
        mentions, so a post-time watermark would permanently drop both. The feed resyncs in full.
        """
        session = MockSession.return_value
        snapshots = _wire(session, [_mentions_page([])])

        _rows(_source("mentions"))

        assert "filters" not in snapshots[0]["json"]
        assert "startDate" not in json.dumps(snapshots[0]["json"])

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_endpoint_replaces_rather_than_merges(self, MockSession) -> None:
        for endpoint in ENDPOINTS:
            resource = _resource(OCTOLENS_ENDPOINTS[endpoint], "v2")
            assert resource["write_disposition"] == "replace"


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_state_is_saved_after_each_yielded_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _mentions_page([{"sourceId": "a"}], next_cursor="c1"),
                _mentions_page([{"sourceId": "b"}], next_cursor=None),
            ],
        )
        manager = _make_manager()

        _rows(_source("mentions", manager))

        manager.save_state.assert_called_once_with(OctolensResumeConfig(cursor="c1"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_the_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_mentions_page([{"sourceId": "z"}])])
        manager = _make_manager(OctolensResumeConfig(cursor="resume-cursor"))

        rows = _rows(_source("mentions", manager))

        assert rows == [{"sourceId": "z"}]
        assert snapshots[0]["json"]["cursor"] == "resume-cursor"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoints_never_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"id": 1}]})])
        manager = _make_manager(OctolensResumeConfig(cursor="stale-mentions-cursor"))

        _rows(_source("keywords", manager))

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()


class TestDimensionEndpoints:
    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("keywords", "/api/v2/keywords"),
            ("feeds", "/api/v2/feeds"),
            ("notifications", "/api/v2/notifications"),
            ("org_members", "/api/v2/org/members"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_get_request_per_endpoint(self, MockSession, endpoint: str, path: str) -> None:
        session = MockSession.return_value
        # A stray cursor in the body must not make these endpoints page — they are not paginated.
        snapshots = _wire(session, [_response({"data": [{"id": 1}], "pagination": {"nextCursor": "c1"}})])

        rows = _rows(_source(endpoint))

        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        assert snapshots[0]["method"] == "GET"
        assert snapshots[0]["url"] == f"{OCTOLENS_BASE_URL}{path}"
        assert snapshots[0]["json"] == {}


class TestSourceResponseShape:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_mentions_partitioned_on_the_stable_post_timestamp(self, MockSession) -> None:
        response = _source("mentions")
        assert response.name == "mentions"
        assert response.primary_keys == ["sourceId"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["timestamp"]

    @pytest.mark.parametrize("endpoint", ["keywords", "feeds", "notifications", "org_members"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_dimension_tables_are_unpartitioned_with_id_keys(self, MockSession, endpoint: str) -> None:
        response = _source(endpoint)
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_declared_endpoint_is_buildable(self, MockSession) -> None:
        for endpoint in ENDPOINTS:
            assert _source(endpoint).primary_keys


class TestHttpErrors:
    @pytest.mark.parametrize("status_code", [401, 403])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failures_raise_a_matchable_error(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": {"code": "UNAUTHORIZED"}}, status_code=status_code)])

        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source("mentions"))
        assert f"{status_code} Client Error" in str(exc.value)


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, raise_json: bool = False) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self._raise_json = raise_json

    def json(self) -> Any:
        if self._raise_json:
            raise ValueError("no json")
        return self._json


class TestCheckAccess:
    @pytest.mark.parametrize(
        "response, expected_status",
        [
            (FakeResponse(json_data={"organizationId": "org_1", "scopes": ["read"]}), 200),
            (FakeResponse(status_code=401, json_data={"error": {"message": "Invalid key"}}), 401),
            (FakeResponse(status_code=403, json_data={"error": {"message": "Insufficient scope"}}), 403),
            (FakeResponse(status_code=500), 500),
            # A 200 that isn't JSON, or one without a workspace, is not a validated key.
            (FakeResponse(raise_json=True), 0),
            (FakeResponse(json_data={"scopes": ["read"]}), 0),
        ],
    )
    def test_status_mapping(self, response: FakeResponse, expected_status: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(OCTOLENS_SESSION_PATCH, return_value=session):
            status, _message = check_access("k", "v2")
        assert status == expected_status

    @pytest.mark.parametrize("status_code, expected", [(401, "Invalid key"), (500, "Boom")])
    def test_surfaces_the_error_envelope_message(self, status_code: int, expected: str) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code=status_code, json_data={"error": {"message": expected}})
        with mock.patch(OCTOLENS_SESSION_PATCH, return_value=session):
            _status, message = check_access("k", "v2")
        assert message == expected

    @pytest.mark.parametrize(
        "response",
        [
            # Not JSON at all (a proxy or maintenance page fronting the error).
            FakeResponse(status_code=500, raise_json=True),
            # JSON, but not the documented error envelope.
            FakeResponse(status_code=500, json_data=["unexpected"]),
            FakeResponse(status_code=500, json_data={"error": "just a string"}),
            FakeResponse(status_code=500, json_data={"error": {"code": "boom"}}),
        ],
    )
    def test_falls_back_to_the_status_code_when_there_is_no_envelope_message(self, response: FakeResponse) -> None:
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(OCTOLENS_SESSION_PATCH, return_value=session):
            status, message = check_access("k", "v2")
        assert status == 500
        assert message == "Octolens returned HTTP 500"

    def test_probes_the_versioned_auth_endpoint_with_a_bearer_token(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(json_data={"organizationId": "org_1"})
        with mock.patch(OCTOLENS_SESSION_PATCH, return_value=session):
            check_access("k", "v2")
        call = session.get.call_args
        assert call.args[0] == f"{OCTOLENS_BASE_URL}/api/v2/auth"
        assert call.kwargs["headers"]["Authorization"] == "Bearer k"

    def test_connection_error_reports_unvalidated(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(OCTOLENS_SESSION_PATCH, return_value=session):
            status, message = check_access("k", "v2")
        assert status == 0
        assert message is not None
