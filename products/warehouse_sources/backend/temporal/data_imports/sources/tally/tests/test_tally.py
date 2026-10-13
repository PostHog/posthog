import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.tally.settings import (
    FORMS_PAGE_SIZE,
    SUBMISSION_FILTER_ALL,
    SUBMISSION_FILTER_COMPLETED,
    SUBMISSIONS_PAGE_SIZE,
    TALLY_API_VERSION,
    TALLY_BASE_URL,
    WEBHOOKS_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.tally import (
    TallyResumeConfig,
    tally_source,
    validate_credentials,
)

CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
TALLY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.tally.tally.make_tracked_session"
)
SLEEP_PATCH = "tenacity.nap.time.sleep"

BASE = TALLY_BASE_URL
FORMS_PAGE_1 = f"{BASE}/forms?limit={FORMS_PAGE_SIZE}&page=1"


def _resp(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _page(rows: list[dict[str, Any]], key: str = "items", has_more: bool = False) -> Response:
    return _resp({key: rows, "page": 1, "limit": 50, "hasMore": has_more})


def _norm(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parts = urlsplit(url)
    return parts.path, tuple(sorted(parse_qsl(parts.query)))


def _make_manager(resume_state: TallyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses_by_url: dict[str, list[Response]]) -> list[dict[str, Any]]:
    session.headers = {}
    normalized: dict[tuple[str, tuple[tuple[str, str], ...]], list[Response]] = {
        _norm(url): list(queue) for url, queue in responses_by_url.items()
    }
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> Any:
        param_snapshots.append(dict(request.params or {}))
        return request.prepare()

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        queue = normalized.get(_norm(prepared.url))
        if not queue:
            raise AssertionError(f"unexpected request url {prepared.url!r}")
        return queue.pop(0)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return param_snapshots


def _run(
    endpoint: str,
    responses_by_url: dict[str, list[Response]],
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], mock.MagicMock]:
    # Endpoints that disable sample capture build their own session in `_client_config`, so patch
    # that factory too and point it at the same wired session the rest client would otherwise use.
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession, mock.patch(TALLY_SESSION_PATCH) as MockTallySession:
        session = MockSession.return_value
        MockTallySession.return_value = session
        params = _wire(session, responses_by_url)
        response = tally_source(
            api_key="key",
            api_version=TALLY_API_VERSION,
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=manager if manager is not None else _make_manager(),
            **kwargs,
        )
        rows = [row for page in cast(Any, response.items()) for row in page]
    return rows, params, session


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("workspaces", ["id"], "createdAt", "asc"),
            ("forms", ["id"], "createdAt", "asc"),
            ("questions", ["formId", "id"], "createdAt", "asc"),
            ("submissions", ["formId", "id"], "submittedAt", "desc"),
            ("webhooks", ["id"], "createdAt", "asc"),
            ("folders", ["workspaceId", "id"], "createdAt", "asc"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_shape(
        self,
        endpoint: str,
        expected_keys: list[str],
        expected_partition_key: str,
        expected_sort_mode: str,
        _MockSession: Any,
    ) -> None:
        response = tally_source(
            api_key="key",
            api_version=TALLY_API_VERSION,
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        # Child tables aggregate rows from every form, so their key must carry the parent form id.
        assert response.primary_keys == expected_keys
        assert response.partition_keys == [expected_partition_key]
        assert response.partition_mode == "datetime"
        # Submissions interleave one form's history after another's, so the stream is not globally
        # ascending and the watermark must only advance once the whole sync finishes.
        assert response.sort_mode == expected_sort_mode


class TestPagination:
    def test_follows_has_more_across_pages(self) -> None:
        responses = {
            FORMS_PAGE_1: [_page([{"id": "F1"}], has_more=True)],
            f"{BASE}/forms?limit={FORMS_PAGE_SIZE}&page=2": [_page([{"id": "F2"}], has_more=False)],
        }
        rows, params, _session = _run("forms", responses)
        assert rows == [{"id": "F1"}, {"id": "F2"}]
        assert params[0]["page"] == 1
        assert params[1]["page"] == 2

    @parameterized.expand(
        [
            ("workspaces", f"{BASE}/workspaces?page=1", "items", None),
            ("forms", FORMS_PAGE_1, "items", FORMS_PAGE_SIZE),
            ("webhooks", f"{BASE}/webhooks?limit={WEBHOOKS_PAGE_SIZE}&page=1", "webhooks", WEBHOOKS_PAGE_SIZE),
        ]
    )
    def test_top_level_endpoint_request_shape(
        self, endpoint: str, url: str, selector: str, expected_limit: int | None
    ) -> None:
        # /workspaces documents no page-size param, so sending one would be an undocumented param;
        # the other two carry the vendor's documented maximum.
        rows, params, _session = _run(endpoint, {url: [_page([{"id": "X"}], key=selector)]})
        assert rows == [{"id": "X"}]
        assert params[0].get("limit") == expected_limit


class TestTopLevelResume:
    def test_resumes_from_saved_page(self) -> None:
        responses = {f"{BASE}/forms?limit={FORMS_PAGE_SIZE}&page=4": [_page([{"id": "F9"}])]}
        rows, params, _session = _run("forms", responses, _make_manager(TallyResumeConfig(next_page=4)))
        assert rows == [{"id": "F9"}]
        assert params[0]["page"] == 4


class TestFanOut:
    @parameterized.expand([(SUBMISSION_FILTER_COMPLETED,), (SUBMISSION_FILTER_ALL,)])
    def test_submission_filter_is_sent_verbatim(self, submission_filter: str) -> None:
        # Tally documents no default for `filter`, so the chosen value must always be sent.
        responses = {
            FORMS_PAGE_1: [_page([{"id": "F1"}])],
            f"{BASE}/forms/F1/submissions?limit={SUBMISSIONS_PAGE_SIZE}&page=1&filter={submission_filter}": [
                _resp({"submissions": [], "hasMore": False})
            ],
        }
        _rows, params, _session = _run("submissions", responses, submission_filter=submission_filter)
        assert params[1]["filter"] == submission_filter

    def test_resume_continues_mid_form_from_the_saved_page(self) -> None:
        responses = {
            FORMS_PAGE_1: [_page([{"id": "F1"}])],
            f"{BASE}/forms/F1/submissions?limit={SUBMISSIONS_PAGE_SIZE}&page=3&filter=completed": [
                _resp({"submissions": [{"id": "S3"}], "hasMore": False})
            ],
        }
        state = TallyResumeConfig(
            fanout_state={"completed": [], "current": "/forms/F1/submissions", "child_state": {"page": 3}}
        )
        rows, params, _session = _run("submissions", responses, _make_manager(state))
        assert rows == [{"id": "S3", "formId": "F1"}]
        assert params[1]["page"] == 3


class TestWebhookSecrets:
    def test_signing_secret_and_headers_are_nulled_and_kept_out_of_capture(self) -> None:
        # Webhook signing secrets and custom auth headers are credentials — persisting them would let
        # anyone with warehouse read access forge signed deliveries or reuse embedded tokens. They
        # must land as null, and the raw responses must stay out of HTTP sample capture.
        session = mock.MagicMock()
        responses = {
            f"{BASE}/webhooks?limit={WEBHOOKS_PAGE_SIZE}&page=1": [
                _page(
                    [
                        {
                            "id": "W1",
                            "url": "https://example.com/hook",
                            "signingSecret": "shh",
                            "httpHeaders": [{"name": "X-Auth", "value": "tok"}],
                        }
                    ],
                    key="webhooks",
                )
            ],
        }
        with mock.patch(TALLY_SESSION_PATCH, return_value=session) as mock_tally_session:
            _wire(session, responses)
            response = tally_source(
                api_key="key",
                api_version=TALLY_API_VERSION,
                endpoint="webhooks",
                team_id=1,
                job_id="job",
                resumable_source_manager=_make_manager(),
            )
            rows = [row for page in cast(Any, response.items()) for row in page]

        assert rows == [{"id": "W1", "url": "https://example.com/hook", "signingSecret": None, "httpHeaders": None}]
        assert mock_tally_session.call_args.kwargs["capture"] is False


class TestIncremental:
    def test_future_watermark_is_clamped_to_now(self) -> None:
        # A watermark ahead of the clock would filter out every submission, syncing nothing forever.
        future = datetime.now(UTC) + timedelta(days=30)
        captured: dict[str, Any] = {}

        def _send(prepared: Any, **_kwargs: Any) -> Response:
            if "/submissions" in prepared.url:
                captured.update(dict(parse_qsl(urlsplit(prepared.url).query)))
                return _resp({"submissions": [], "hasMore": False})
            return _page([{"id": "F1"}])

        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.headers = {}
            session.prepare_request.side_effect = lambda request: request.prepare()
            session.send.side_effect = _send
            response = tally_source(
                api_key="key",
                api_version=TALLY_API_VERSION,
                endpoint="submissions",
                team_id=1,
                job_id="job",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=future,
            )
            list(cast(Any, response.items()))

        assert captured["startDate"] < future.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestRetryClassification:
    @parameterized.expand([(429,), (500,), (503,)])
    @mock.patch(SLEEP_PATCH)
    def test_transient_status_is_retried(self, status: int, _sleep: Any) -> None:
        responses = {FORMS_PAGE_1: [_resp({"error": "later"}, status=status), _page([{"id": "F1"}])]}
        rows, _params, _session = _run("forms", responses)
        assert rows == [{"id": "F1"}]

    @parameterized.expand([(401,), (403,)])
    @mock.patch(SLEEP_PATCH)
    def test_credential_error_fails_loud(self, status: int, _sleep: Any) -> None:
        responses = {FORMS_PAGE_1: [_resp({"error": "nope"}, status=status)]}
        with pytest.raises(requests.HTTPError):
            _run("forms", responses)


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(TALLY_SESSION_PATCH)
    def test_status_mapping(self, status: int, expected_ok: bool, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, returned_status = validate_credentials("key")
        assert ok is expected_ok
        assert returned_status == status
