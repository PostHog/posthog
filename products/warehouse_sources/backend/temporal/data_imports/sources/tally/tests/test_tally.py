from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tally import TallySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.settings import (
    FORMS_PAGE_SIZE,
    SUBMISSION_FILTER_ALL,
    SUBMISSION_FILTER_COMPLETED,
    SUBMISSIONS_PAGE_SIZE,
    TALLY_BASE_URL,
    WEBHOOKS_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.source import TallySource
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.tally import TallyResumeConfig

BASE = TALLY_BASE_URL
FORMS_PAGE_1 = f"{BASE}/forms?limit={FORMS_PAGE_SIZE}&page=1"


def _resp(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _page(rows: list[dict[str, Any]], key: str = "items", has_more: bool = False) -> ScriptedResponse:
    return _resp({key: rows, "page": 1, "limit": 50, "hasMore": has_more})


def _norm(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parts = urlsplit(url)
    return parts.path, tuple(sorted(parse_qsl(parts.query)))


def _driver(submission_filter: Literal["completed", "all"] = SUBMISSION_FILTER_COMPLETED) -> SourceDriver:
    return SourceDriver(TallySource(), TallySourceConfig(api_key="key", submission_filter=submission_filter))


def _by_url(responses_by_url: dict[str, list[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    normalized = {_norm(url): list(queue) for url, queue in responses_by_url.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue = normalized.get(_norm(request.url))
        if not queue:
            raise UnexpectedRequest(f"unexpected request url {request.url!r}")
        return queue.pop(0)

    return respond


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
    def test_shape(
        self,
        endpoint: str,
        expected_keys: list[str],
        expected_partition_key: str,
        expected_sort_mode: str,
    ) -> None:
        empty: dict[str, list[Any]] = {key: [] for key in ("items", "webhooks", "submissions", "questions", "folders")}
        response = _driver().run(endpoint, always(_resp({**empty, "hasMore": False}))).response
        assert response is not None
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
        result = _driver().run("forms", _by_url(responses))
        assert result.rows == [{"id": "F1"}, {"id": "F2"}]
        assert result.params("page") == ["1", "2"]

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
        result = _driver().run(endpoint, _by_url({url: [_page([{"id": "X"}], key=selector)]}))
        assert result.rows == [{"id": "X"}]
        assert result.requests[0].param("limit") == (str(expected_limit) if expected_limit is not None else None)


class TestTopLevelResume:
    def test_resumes_from_saved_page(self) -> None:
        responses = {f"{BASE}/forms?limit={FORMS_PAGE_SIZE}&page=4": [_page([{"id": "F9"}])]}
        result = _driver().run("forms", _by_url(responses), resume_state=TallyResumeConfig(next_page=4))
        assert result.rows == [{"id": "F9"}]
        assert result.params("page") == ["4"]


class TestFanOut:
    @parameterized.expand([(SUBMISSION_FILTER_COMPLETED,), (SUBMISSION_FILTER_ALL,)])
    def test_submission_filter_is_sent_verbatim(self, submission_filter: Literal["completed", "all"]) -> None:
        # Tally documents no default for `filter`, so the chosen value must always be sent.
        responses = {
            FORMS_PAGE_1: [_page([{"id": "F1"}])],
            f"{BASE}/forms/F1/submissions?limit={SUBMISSIONS_PAGE_SIZE}&page=1&filter={submission_filter}": [
                _resp({"submissions": [], "hasMore": False})
            ],
        }
        result = _driver(submission_filter).run("submissions", _by_url(responses))
        assert result.requests[1].param("filter") == submission_filter

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
        result = _driver().run("submissions", _by_url(responses), resume_state=state)
        assert result.rows == [{"id": "S3", "formId": "F1"}]
        assert result.requests[1].param("page") == "3"


class TestWebhookSecrets:
    def test_signing_secret_and_headers_are_nulled_and_kept_out_of_capture(self) -> None:
        # Webhook signing secrets and custom auth headers are credentials — persisting them would let
        # anyone with warehouse read access forge signed deliveries or reuse embedded tokens. They
        # must land as null, and the raw responses must stay out of HTTP sample capture.
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
        result = _driver().run("webhooks", _by_url(responses))

        assert result.rows == [
            {"id": "W1", "url": "https://example.com/hook", "signingSecret": None, "httpHeaders": None}
        ]
        assert result.session_options
        assert all(options["capture"] is False for options in result.session_options)


class TestIncremental:
    def test_future_watermark_is_clamped_to_now(self) -> None:
        # A watermark ahead of the clock would filter out every submission, syncing nothing forever.
        future = datetime.now(UTC) + timedelta(days=30)

        def script(request: RecordedRequest) -> ScriptedResponse:
            if "/submissions" in request.path:
                return _resp({"submissions": [], "hasMore": False})
            return _page([{"id": "F1"}])

        result = _driver().run(
            "submissions",
            script,
            should_use_incremental_field=True,
            db_incremental_field_last_value=future,
            incremental_field="submittedAt",
        )

        submissions = [request for request in result.requests if "/submissions" in request.path]
        start_date = submissions[0].param("startDate")
        assert start_date is not None
        assert start_date < future.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestRetryClassification:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_transient_status_is_retried(self, status: int) -> None:
        responses = {FORMS_PAGE_1: [_resp({"error": "later"}, status=status), _page([{"id": "F1"}])]}
        result = _driver().run("forms", _by_url(responses))
        assert result.rows == [{"id": "F1"}]

    @parameterized.expand([(401,), (403,)])
    def test_credential_error_fails_loud(self, status: int) -> None:
        responses = {FORMS_PAGE_1: [_resp({"error": "nope"}, status=status)]}
        result = _driver().run("forms", _by_url(responses))
        assert isinstance(result.raised, requests.HTTPError)
