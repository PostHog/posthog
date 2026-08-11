import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.okendo import (
    OkendoResumeConfig,
    okendo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.settings import (
    OKENDO_API_VERSION,
    REVIEW_STATUSES,
)

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
OKENDO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.okendo.okendo.make_tracked_session"
)


def _response(body: dict[str, Any] | None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body if body is not None else {}).encode()
    return resp


def _reviews_page(ids: list[str], next_cursor: str | None = None) -> Response:
    body: dict[str, Any] = {"reviews": [{"reviewId": review_id} for review_id in ids]}
    if next_cursor is not None:
        body["nextUrl"] = f"/enterprise/reviews?limit=100&lastEvaluated={next_cursor}"
    return _response(body)


def _make_manager(resume_state: OkendoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so reading it after the run shows
    only the final state — snapshot a copy as each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


def _source(endpoint: str, manager: mock.MagicMock) -> SourceResponse:
    return okendo_source(
        user_id="user-1",
        api_key="key-1",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        api_version=OKENDO_API_VERSION,
        resumable_source_manager=manager,
    )


class TestReviewsTransport:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_every_moderation_status_and_follows_the_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _reviews_page(["a1"], next_cursor="cursor-1"),
                _reviews_page(["a2"]),
                _reviews_page(["p1"]),
                _reviews_page(["r1"]),
            ],
        )

        rows = _rows(_source("reviews", _make_manager()))

        # Only 'approved' comes back when `status` is unset, so a lost fan-out silently drops the
        # moderation queue; a mis-parsed `nextUrl` silently drops every page after the first.
        assert [row["reviewId"] for row in rows] == ["a1", "a2", "p1", "r1"]
        assert [p["status"] for p in params] == ["approved", "approved", "pending", "rejected"]
        assert params[1]["lastEvaluated"] == "cursor-1"
        assert "lastEvaluated" not in params[2]
        assert params[0]["limit"] == 100
        assert params[0]["orderBy"] == "date asc"

    @parameterized.expand(
        [
            ("no_next_url", None),
            ("next_url_without_cursor", "/enterprise/reviews?limit=100"),
            ("next_url_repeating_the_sent_cursor", "/enterprise/reviews?lastEvaluated=cursor-1"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pagination_terminates(self, _name: str, next_url: str | None, MockSession) -> None:
        session = MockSession.return_value
        first: dict[str, Any] = {"reviews": [{"reviewId": "a1"}]}
        if next_url is not None:
            first["nextUrl"] = next_url
        _wire(session, [_response(first), _reviews_page(["p1"]), _reviews_page(["r1"])])

        # Seeded so the repeated-cursor case sends the cursor the response then echoes back.
        manager = _make_manager(OkendoResumeConfig(variant="approved", last_evaluated="cursor-1"))
        rows = _rows(_source("reviews", manager))

        # One request per status: the run ends rather than looping on an unusable next link. A
        # fourth request would exhaust the wired responses and raise StopIteration.
        assert session.send.call_count == len(REVIEW_STATUSES)
        assert len(rows) == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_statuses_and_seeds_the_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_reviews_page(["p2"]), _reviews_page(["r1"])])

        manager = _make_manager(OkendoResumeConfig(variant="pending", last_evaluated="cursor-9"))
        _rows(_source("reviews", manager))

        assert [p["status"] for p in params] == ["pending", "rejected"]
        assert params[0]["lastEvaluated"] == "cursor-9"
        # The cursor belongs to the status it was saved against; carrying it into the next one
        # would resume that status part-way through and drop its earlier rows.
        assert "lastEvaluated" not in params[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_the_next_page_then_the_next_status(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _reviews_page(["a1"], next_cursor="cursor-1"),
                _reviews_page(["a2"]),
                _reviews_page(["p1"]),
                _reviews_page(["r1"]),
            ],
        )

        manager = _make_manager()
        _rows(_source("reviews", manager))

        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            OkendoResumeConfig(variant="approved", last_evaluated="cursor-1"),
            OkendoResumeConfig(variant="pending", last_evaluated=None),
            OkendoResumeConfig(variant="rejected", last_evaluated=None),
        ]


class TestEndpointRequests:
    @parameterized.expand(
        [
            ("loyalty_earning_rules", "/loyalty/earning_rules"),
            ("loyalty_redemption_rules", "/loyalty/redemption_rules"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rule_catalogs_are_read_as_a_single_page(self, endpoint: str, _path: str, MockSession) -> None:
        session = MockSession.return_value
        # A nextUrl here must be ignored: neither rules endpoint documents limit/lastEvaluated, so
        # replaying a cursor against them would loop on the same page.
        params = _wire(
            session, [_response({"rules": [{"type": "points-per-spend"}], "nextUrl": "/enterprise/x?lastEvaluated=c"})]
        )

        rows = _rows(_source(endpoint, _make_manager()))

        assert len(rows) == 1
        assert session.send.call_count == 1
        assert "limit" not in params[0]
        assert "status" not in params[0]

    @parameterized.expand(
        [
            ("reviews", ["reviewId"], ["dateCreated"]),
            ("loyalty_earning_rules", ["type"], None),
            ("loyalty_redemption_rules", ["redemptionRuleId"], None),
        ]
    )
    def test_primary_and_partition_keys(
        self, endpoint: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        # Okendo rows carry no `id`, so a key copied from another source would be null for every
        # row and every merge would multi-match.
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_header_is_sent(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_reviews_page(["a1"]), _reviews_page([]), _reviews_page([])])

        _rows(_source("reviews", _make_manager()))

        # The API rejects requests without it.
        assert session.headers.get("okendo-api-version") == OKENDO_API_VERSION

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_response_shape_fails_loud(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [{"reviewId": "a1"}]})])

        # A renamed row key must not read as "0 rows synced".
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("reviews", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_body_is_an_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}), _response({}), _response({})])

        assert _rows(_source("reviews", _make_manager())) == []


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(OKENDO_SESSION_PATCH)
    def test_reports_the_probe_status(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        # The status is returned, not just a bool, so the source can accept 403 at connect time.
        assert validate_credentials("user-1", "key-1", OKENDO_API_VERSION) == (expected, status_code)

    @mock.patch(OKENDO_SESSION_PATCH)
    def test_transport_failure_does_not_raise(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("user-1", "key-1", OKENDO_API_VERSION) == (False, None)
