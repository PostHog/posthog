from typing import Any

import pytest
import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zonkafeedback import (
    ZonkaFeedbackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.source import ZonkaFeedbackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.zonka_feedback import (
    ZonkaFeedbackResumeConfig,
    base_url,
    check_access,
)


def _response(items: list[dict[str, Any]] | None, *, drop_result: bool = False, status: int = 200) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_result:
        body["result"] = items or []
    return ScriptedResponse(status=status, json=body)


def _redirect(location: str = "https://evil.example.com/") -> ScriptedResponse:
    return ScriptedResponse(status=302, headers={"Location": location}, body=b"{}")


def _run(
    script: Any, endpoint: str = "responses", resume_state: ZonkaFeedbackResumeConfig | None = None, **inputs: Any
) -> DriveResult:
    driver = SourceDriver(ZonkaFeedbackSource(), ZonkaFeedbackSourceConfig(auth_token="zonka-token", data_center="us1"))
    return driver.run(endpoint, script, resume_state=resume_state, **inputs)


SURVEY_PAGES: dict[int, list[dict[str, Any]]] = {1: [{"id": "s2"}, {"id": "s1"}], 2: [{"id": "s3"}, {"name": "no id"}]}
LOG_EMAIL_FIRST = {
    "to": "ana@example.com",
    "sentDateTime": "2026-03-02T10:00:00.000Z",
    "surveyId": "s1",
    "channel": "email",
    "emailOpened": None,
    "status": "noResponse",
}
LOG_EMAIL_SECOND = {**LOG_EMAIL_FIRST, "to": "ben@example.com", "sentDateTime": "2026-03-01T09:00:00.000Z"}
LOG_WHATSAPP_NO_KEYS = {"to": "+15550100", "sentDateTime": "2026-02-27T08:00:00.000Z", "status": "responded"}
LOG_PAGES: dict[tuple[str, str, int], list[dict[str, Any]]] = {
    ("s1", "email", 1): [LOG_EMAIL_FIRST],
    ("s1", "email", 2): [LOG_EMAIL_SECOND],
    ("s3", "whatsapp", 1): [LOG_WHATSAPP_NO_KEYS],
}


def _zonka_account(request: RecordedRequest) -> ScriptedResponse:
    page = int(request.param("page") or 1)
    if request.path == "/surveys":
        return _response(SURVEY_PAGES.get(page, []))
    assert request.path == "/distribution-logs"
    key = (request.param("surveyId") or "", request.param("channel") or "", page)
    return _response(LOG_PAGES.get(key, []))


def _log_requests(result: DriveResult) -> list[tuple[str | None, str | None, str | None]]:
    return [
        (request.param("surveyId"), request.param("channel"), request.param("page"))
        for request in result.requests
        if request.path == "/distribution-logs"
    ]


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        # Page 1 must never be fetched on resume — only pages from the saved bookmark onward.
        result = _run([_response([{"id": 2}]), _response([])], resume_state=ZonkaFeedbackResumeConfig(next_page=2))

        assert result.rows == [{"id": 2}]
        assert result.params("page")[0] == "2"

    def test_missing_result_key_raises_loudly(self) -> None:
        result = _run([_response(None, drop_result=True)])

        # A 200 body without "result" means the response shape changed — fail loud, not silently 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    def test_auth_failure_fails_loud(self) -> None:
        result = _run([_response([], status=401)])

        # An invalid/revoked token surfaces as a permanent HTTPError; retrying can't fix credentials.
        assert isinstance(result.raised, requests.HTTPError)


class TestSessionSecurity:
    """Credentialed requests must reject a 3xx so a redirect from a compromised host can't retarget
    the bearer token at another origin (the source pins the client with allow_redirects=False)."""

    def test_redirect_is_rejected(self) -> None:
        result = _run([_redirect()])

        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "us1", "https://us1.apis.zonkafeedback.com"),
            ("eu", "e", "https://e.apis.zonkafeedback.com"),
            ("in", "in", "https://in.apis.zonkafeedback.com"),
        ]
    )
    def test_base_url_per_data_center(self, _name: str, data_center: str, expected: str) -> None:
        assert base_url(data_center) == expected

    @parameterized.expand(
        [
            ("path_delimiter", "us1/evil.com"),
            ("fragment", "us1#@evil.com"),
            ("userinfo", "us1@evil.com"),
            ("unknown_region", "au"),
            ("empty", ""),
        ]
    )
    def test_base_url_rejects_unlisted_data_center(self, _name: str, data_center: str) -> None:
        # A `data_center` outside the allowlist could otherwise retarget the credentialed request at
        # an attacker host and leak the bearer token.
        with pytest.raises(ValueError, match="Unknown Zonka Feedback data center"):
            base_url(data_center)


class TestCheckAccess:
    def test_probe_redacts_token_and_pins_redirects(self) -> None:
        with scripted_network(always(ScriptedResponse(json={}))) as network:
            check_access("secret-token", "us1")
        assert network.session_options[0]["redact_values"] == ("secret-token",)
        assert network.session_options[0]["allow_redirects"] is False


class TestZonkaFeedbackSourceResponse:
    @parameterized.expand([("responses",), ("surveys",), ("contacts",), ("survey_links",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _run(always(_response([])), endpoint=endpoint)
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No endpoint exposes a stable creation timestamp we can safely partition on.
        assert response.partition_mode is None
        assert response.partition_keys is None

    @parameterized.expand(
        [
            ("paginated", "locations", [[{"id": "l1"}], [{"id": "l2"}], []], ["1", "2", "3"]),
            # A page-number walk on an endpoint that ignores `page` would fetch the same list forever.
            ("unpaginated", "workspaces", [[{"id": "w1"}, {"id": "w2"}]], [None]),
        ]
    )
    def test_list_endpoint_walk(
        self, _name: str, endpoint: str, pages: list[list[dict[str, Any]]], expected_pages: list[str | None]
    ) -> None:
        result = _run([_response(page) for page in pages], endpoint=endpoint)

        assert result.raised is None
        assert result.rows == [row for page in pages for row in page]
        assert result.params("page") == expected_pages


def _state(survey_id: str, channel: str, page: int, end_date: str = "2026-06-01") -> ZonkaFeedbackResumeConfig:
    return ZonkaFeedbackResumeConfig(next_page=page, survey_id=survey_id, channel=channel, end_date=end_date)


class TestDistributionLogs:
    @time_machine.travel("2026-06-01T23:30:00Z", tick=False)
    def test_walks_every_survey_and_channel(self) -> None:
        result = _run(_zonka_account, endpoint="distribution_logs")

        assert result.raised is None
        assert result.params("page")[:3] == ["1", "2", "3"]
        assert _log_requests(result) == [
            ("s1", "email", "1"),
            ("s1", "email", "2"),
            ("s1", "email", "3"),
            ("s1", "sms", "1"),
            ("s1", "whatsapp", "1"),
            ("s2", "email", "1"),
            ("s2", "sms", "1"),
            ("s2", "whatsapp", "1"),
            ("s3", "email", "1"),
            ("s3", "sms", "1"),
            ("s3", "whatsapp", "1"),
            ("s3", "whatsapp", "2"),
        ]
        assert result.rows == [
            LOG_EMAIL_FIRST,
            LOG_EMAIL_SECOND,
            {"surveyId": "s3", "channel": "whatsapp", **LOG_WHATSAPP_NO_KEYS},
        ]
        # Each pair is saved before it is read, so a pair with no rows still moves the saved cursor on.
        assert result.committed_states == [
            _state("s1", "email", 1),
            _state("s1", "email", 2),
            _state("s1", "email", 3),
            _state("s1", "sms", 1),
            _state("s1", "whatsapp", 1),
            _state("s2", "email", 1),
            _state("s2", "sms", 1),
            _state("s2", "whatsapp", 1),
            _state("s3", "email", 1),
            _state("s3", "sms", 1),
            _state("s3", "whatsapp", 1),
            _state("s3", "whatsapp", 2),
        ]
        assert result.completed_state is None

    @time_machine.travel("2026-06-01T23:30:00Z", tick=False)
    def test_resume_keeps_the_saved_end_date(self) -> None:
        result = _run(_zonka_account, endpoint="distribution_logs", resume_state=_state("s1", "email", 2, "2026-05-30"))

        assert result.raised is None
        log_requests = [request for request in result.requests if request.path == "/distribution-logs"]
        assert {request.param("endDate") for request in log_requests} == {"2026-05-30"}

    @parameterized.expand(
        [
            ("mid_pair", ZonkaFeedbackResumeConfig(next_page=2, survey_id="s1", channel="email"), ("s1", "email", "2")),
            (
                "later_channel",
                ZonkaFeedbackResumeConfig(next_page=1, survey_id="s3", channel="sms"),
                ("s3", "sms", "1"),
            ),
            (
                "survey_deleted_since",
                ZonkaFeedbackResumeConfig(next_page=4, survey_id="s15", channel="sms"),
                ("s2", "email", "1"),
            ),
            ("past_last_pair", ZonkaFeedbackResumeConfig(next_page=2, survey_id="s9", channel="email"), None),
        ]
    )
    def test_resumes_from_saved_pair(
        self,
        _name: str,
        resume_state: ZonkaFeedbackResumeConfig,
        expected_first_request: tuple[str, str, str] | None,
    ) -> None:
        result = _run(_zonka_account, endpoint="distribution_logs", resume_state=resume_state)

        assert result.raised is None
        log_requests = _log_requests(result)
        assert (log_requests[0] if log_requests else None) == expected_first_request
        assert ("s1", "email", "1") not in log_requests

    @parameterized.expand(
        [
            ("full_refresh", {}, "2010-01-01"),
            (
                "incremental",
                {"incremental_field": "sentDateTime", "db_incremental_field_last_value": "2026-03-05T00:30:00Z"},
                "2026-03-04",
            ),
            (
                "full_refresh_ignores_stale_watermark",
                {
                    "incremental_field": "sentDateTime",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": "2026-03-05T00:30:00Z",
                },
                "2010-01-01",
            ),
        ]
    )
    @time_machine.travel("2026-06-01T23:30:00Z", tick=False)
    def test_date_window(self, _name: str, inputs: dict[str, Any], expected_start: str) -> None:
        result = _run(_zonka_account, endpoint="distribution_logs", **inputs)

        assert result.raised is None
        log_requests = [request for request in result.requests if request.path == "/distribution-logs"]
        assert {request.param("startDate") for request in log_requests} == {expected_start}
        assert {request.param("endDate") for request in log_requests} == {"2026-06-01"}

    def test_unparseable_watermark_fails_loud(self) -> None:
        result = _run(
            _zonka_account,
            endpoint="distribution_logs",
            incremental_field="sentDateTime",
            db_incremental_field_last_value="not a date",
        )

        assert isinstance(result.raised, ValueError)
        assert result.requests == []
