import re
import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache, caches
from django.test import override_settings

import requests
from django_redis.cache import RedisCache
from parameterized import parameterized
from prometheus_client import REGISTRY
from requests.structures import CaseInsensitiveDict
from rest_framework import status
from rest_framework.test import APIClient

from posthog import rate_limit
from posthog.models import ProjectSecretAPIKey
from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret
from posthog.plugins.plugin_server_api import WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE
from posthog.test.lagging_redis_reader import lagging_reader_caches, unique_key_prefix

from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.presentation.views.message_templates import (
    EMAIL_BATCH_FLAG,
    EMAIL_FROM_CODE_FLAG,
    TRANSACTIONAL_EMAIL_API_FLAG,
    TransactionalEmailBurstThrottle,
    TransactionalEmailSustainedThrottle,
    TransactionalEmailTeamBurstThrottle,
    TransactionalEmailTeamSustainedThrottle,
)
from products.messaging.backend.services import transactional_email
from products.messaging.backend.services.transactional_email import (
    BATCH_SANDBOX_SENDER_WARNING,
    SANDBOX_SENDER_WARNING,
    make_transactional,
)
from products.messaging.backend.services.transactional_email_status import keyed_message_id
from products.messaging.backend.tests.fake_cdp_api import FakeAnalytics, _response
from products.workflows.backend.facade.api import set_default_email_sender_if_unset
from products.workflows.backend.facade.models import HogFlow
from products.workflows.backend.facade.team_extension import TeamWorkflowsConfig

BATCH_URL = "/api/messaging/send/email_batch/"
SINGLE_URL = "/api/messaging/send/email/"
QUEUED_BODY: dict[str, Any] = {
    "status": "queued",
    "scheduled_at": None,
    "replayed": False,
    "attachment_count": 0,
    "attachment_bytes": 0,
}
RECIPIENT = {"to": "a@example.com", "idempotency_key": "key-a"}
SEND_EVENT = "transactional email api send"

WHOLE_CALL_REFUSALS = [
    ("batch_unavailable", 409, "batch_unavailable", 409, True),
    ("quota_limited", 429, "quota_limited", 429, True),
    ("sending_suspended", 422, "sending_suspended", 422, True),
    ("sending_paused", 422, "sending_paused", 422, True),
    ("sandbox_sender_unavailable", 403, "sandbox_sender_unavailable", 403, True),
    ("sandbox_fields_unsupported", 400, "invalid_request", 400, False),
    ("not_sendable", 400, "transactional_email_paused", 400, True),
    ("invalid_request", 400, "invalid_request", 400, True),
    ("Expected string, received number", 400, "invalid_request", 400, True),
    ("too_large", 413, "content_too_large", 413, False),
]
RECIPIENT_REFUSALS = [
    ("idempotency_key_reused", 422, "idempotency_key_reused", 422),
    ("sandbox_recipient_not_member", 422, "sandbox_recipient_not_member", 422),
    ("invalid_request", 400, "invalid_request", 400),
    ("Expected string, received number", 400, "invalid_recipient", 400),
    ("message_too_large", 413, "content_too_large", 400),
    ("intake_unavailable", 503, "delivery_unavailable", 503),
]

BATCH_WIRE = {
    "template": (
        "/transactional_email/batch",
        {"variables", "recipients"},
        {"to", "distinct_id", "idempotency_key", "variables"},
    ),
    "code": (
        "/transactional_email/send/batch",
        {"variables", "send", "recipients"},
        {"to", "distinct_id", "idempotency_key"},
    ),
}


def _slot_request(forwarded: dict[str, Any], recipient: dict[str, Any]) -> dict[str, Any]:
    slot = {**recipient, "variables": {**forwarded.get("variables", {}), **recipient.get("variables", {})}}
    return {**slot, "send": forwarded["send"]} if "send" in forwarded else slot


def _sent_by(sender_kind: str | None) -> dict[str, str]:
    return {"sender_kind": sender_kind} if sender_kind else {}


def _accepted(message_id: str, **body: Any) -> dict[str, Any]:
    return {"status": 202, "body": {**QUEUED_BODY, "invocation_id": message_id, **body}}


def _batch_answer(*results: dict[str, Any]) -> requests.Response:
    return _response(200, {"results": list(results)})


def _flag_stage_samples() -> float:
    return (
        REGISTRY.get_sample_value(
            "messaging_transactional_email_stage_duration_seconds_count", {"stage": "feature_flag"}
        )
        or 0
    )


def _forwarded(call: Any) -> dict[str, Any]:
    return call.kwargs["json"] if call.kwargs.get("json") is not None else json.loads(call.kwargs["data"])


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.message_templates.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestTransactionalEmailBatch(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, self.sender.id)
        self.template = MessageTemplate.objects.create(
            team=self.team,
            name="Password reset",
            content={"email": {"subject": "Reset your password", "html": "<a href='{{ variables.link }}'>Reset</a>"}},
            type="email",
        )
        self.hog_flow_id = make_transactional(
            self.team.id, self.template.id, user_id=self.user.id, from_integration_id=None
        )
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="batch sends",
            secure_value=hash_key_value(raw_token),
            scopes=["transactional_email:write"],
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        self.psak = APIClient()
        self.psak.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _email(self, form: str) -> dict[str, Any]:
        if form == "code":
            return {"template_key": "welcome", "subject": "Welcome", "html": "<p>Hi</p>"}
        return {"template_id": str(self.template.id), "message_data": {"link": "https://example.com/a", "n": 1}}

    def _enforce_rate_limits(self) -> Any:
        rate_limit.is_rate_limit_enabled.cache_clear()
        rate_limit.get_team_allow_list.cache_clear()
        self.addCleanup(rate_limit.is_rate_limit_enabled.cache_clear)
        self.addCleanup(rate_limit.get_team_allow_list.cache_clear)
        return override_instance_config("RATE_LIMIT_ENABLED", True)

    def _id(self, key: str) -> str:
        return str(keyed_message_id(self.team.id, key))

    def _queued_answer(self, count: int) -> requests.Response:
        return _batch_answer(*(_accepted(self._id(f"key-{index}")) for index in range(count)))

    def _recipients(self, count: int) -> list[dict[str, Any]]:
        return [{"to": f"user{index}@example.com", "idempotency_key": f"key-{index}"} for index in range(count)]

    def _batch(self, form: str = "template", recipients: list[dict[str, Any]] | None = None, /, **fields: Any) -> Any:
        body = {**self._email(form), "recipients": recipients or self._recipients(2), **fields}
        return self.psak.post(BATCH_URL, json.dumps(body), content_type="application/json")

    def _single(self, form: str = "template", **fields: Any) -> Any:
        body = {**self._email(form), "to": "user0@example.com", **fields}
        return self.psak.post(SINGLE_URL, body, format="json", headers={"Idempotency-Key": "key-0"})

    def _archive(self, hog_flow_id: Any) -> None:
        HogFlow.objects.filter(team=self.team, id=hog_flow_id).update(status="archived")

    @parameterized.expand([("template",), ("code",)])
    def test_each_recipient_is_forwarded_as_a_single_send_to_it_would_be(self, mock_post, _flag, capture, form):
        analytics = FakeAnalytics()
        capture.side_effect = analytics.capture
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "single"})
        merged_data = {"message_data": {"link": "https://example.com/a", "n": 2}} if form == "template" else {}
        assert self._single(form, distinct_id="user-0", **merged_data).status_code == status.HTTP_202_ACCEPTED
        single = _forwarded(mock_post.call_args)
        mock_post.return_value = self._queued_answer(2)
        first_recipient: dict[str, Any] = {
            "to": "user0@example.com",
            "distinct_id": "user-0",
            "idempotency_key": "key-0",
        }
        if form == "template":
            first_recipient["message_data"] = {"n": 2}

        response = self._batch(form, [first_recipient, {"to": "user1@example.com", "idempotency_key": "key-1"}])

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "results": [
                {"message_id": self._id("key-0"), "status": "queued", "replayed": False},
                {"message_id": self._id("key-1"), "status": "queued", "replayed": False},
            ]
        }
        url, forwarded = mock_post.call_args.args[0], _forwarded(mock_post.call_args)
        route, shared_fields, recipient_fields = BATCH_WIRE[form]
        assert url.endswith(route)
        assert set(forwarded) <= shared_fields
        assert all(set(recipient) <= recipient_fields for recipient in forwarded["recipients"])
        first, second = (_slot_request(forwarded, recipient) for recipient in forwarded["recipients"])
        assert first == single
        assert second == {
            **single,
            "to": "user1@example.com",
            "distinct_id": "user1@example.com",
            "idempotency_key": "key-1",
            "variables": forwarded.get("variables", {}),
        }
        single_event, *batch_events = analytics.properties_of(SEND_EVENT)
        assert {"batch_size", "batch_id"}.isdisjoint(single_event)
        assert [(event["batch_size"], event["outcome"], event["has_idempotency_key"]) for event in batch_events] == [
            (2, "queued", True)
        ] * 2
        assert batch_events[0]["batch_id"] == batch_events[1]["batch_id"]

    def test_a_batch_times_its_flag_checks_as_one_sample_as_a_single_send_does(self, mock_post, _flag, _capture):
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "single"})
        before_single = _flag_stage_samples()
        assert self._single().status_code == status.HTTP_202_ACCEPTED
        before_batch = _flag_stage_samples()
        mock_post.return_value = self._queued_answer(2)

        assert self._batch().status_code == status.HTTP_200_OK

        assert _flag_stage_samples() - before_batch == before_batch - before_single == 1

    def test_each_forward_carries_a_token_for_its_own_route(self, mock_post, _flag, _capture):
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "single"})
        self._single("template")
        self._single("code")
        mock_post.return_value = self._queued_answer(2)
        self._batch("template")
        self._batch("code")

        forwards = []
        for call in mock_post.call_args_list:
            path = call.args[0].split("/api/projects/")[1]
            match = re.fullmatch(r"(\d+)/hog_flows/([^/]+)/transactional_email(.*)", path)
            assert match is not None
            team_id, hog_flow_id, route = match.groups()
            headers = CaseInsensitiveDict(call.kwargs["headers"])
            scheme, token = headers["Authorization"].split(" ", 1)
            assert scheme == "Bearer"
            claims = WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE.verify(token)
            assert (claims["team_id"], claims["hog_flow_id"]) == (int(team_id), hog_flow_id)
            assert headers.get("Content-Encoding", "identity") == "identity"
            forwards.append((route, claims.get("kind")))
        assert forwards == [
            ("", None),
            ("/send", "code_send"),
            ("/batch", "template_batch"),
            ("/send/batch", "code_send_batch"),
        ]

    def test_a_recipient_the_pipeline_cannot_address_fails_only_its_own_result(self, mock_post, _flag, _capture):
        mock_post.return_value = _batch_answer(_accepted(self._id("key-1")))
        recipients: list[dict[str, Any]] = [
            {"to": "{{person.email}}@example.com", "idempotency_key": "key-0"},
            {"to": "user1@example.com", "idempotency_key": "key-1"},
            {"to": "not an address", "idempotency_key": "key-2"},
        ]

        response = self._batch("template", recipients)

        assert response.status_code == status.HTTP_200_OK, response.json()
        refused, queued, malformed = response.json()["results"]
        assert (refused["error"]["code"], refused["error"]["status"], refused["error"]["retryable"]) == (
            "invalid_recipient",
            400,
            False,
        )
        assert "{ or }" in refused["error"]["detail"]
        assert queued == {"message_id": self._id("key-1"), "status": "queued", "replayed": False}
        assert malformed["error"]["code"] == "invalid_recipient"
        assert [refused["message_id"], malformed["message_id"]] == [self._id("key-0"), self._id("key-2")]
        assert [recipient["to"] for recipient in _forwarded(mock_post.call_args)["recipients"]] == ["user1@example.com"]

    @parameterized.expand(
        [
            (
                "missing_key",
                "template",
                {"recipients": [{"to": "a@example.com"}]},
                "recipients__0__idempotency_key",
            ),
            (
                "key_with_spaces",
                "template",
                {"recipients": [{**RECIPIENT, "idempotency_key": "a b"}]},
                "recipients__0__idempotency_key",
            ),
            (
                "too_many_recipients",
                "template",
                {"recipients": [{"to": "a@example.com", "idempotency_key": f"key-{i}"} for i in range(101)]},
                "recipients",
            ),
            (
                "too_many_recipients_before_their_fields",
                "template",
                {"recipients": [{"to": "a@example.com"} for _ in range(101)]},
                "recipients",
            ),
            ("shared_scheduled_at", "code", {"scheduled_at": "2030-01-01T00:00:00Z"}, "scheduled_at"),
            ("shared_to", "template", {"to": "a@example.com"}, "to"),
            ("shared_distinct_id", "code", {"distinct_id": "person-1"}, "distinct_id"),
            ("shared_unknown_field", "template", {"mesage_data": {"link": "https://example.com/a"}}, "mesage_data"),
            ("shared_legacy_identifiers", "template", {"identifiers": {"distinct_id": "person-1"}}, "identifiers"),
            ("shared_attachments", "template", {"attachments": []}, "attachments"),
            ("shared_code_field_with_template_id", "template", {"subject": "Hi"}, "subject"),
            (
                "recipient_unknown_field",
                "template",
                {"recipients": [{**RECIPIENT, "identifiers": {"distinct_id": "person-1"}}]},
                "recipients__0__identifiers",
            ),
            ("recipient_cc", "code", {"recipients": [{**RECIPIENT, "cc": []}]}, "recipients__0__cc"),
            ("shared_field_name_not_valid_unicode", "template", {"\ud800": 1}, "\\ud800"),
            (
                "recipient_field_name_not_valid_unicode",
                "template",
                {"recipients": [{**RECIPIENT, "\ud800": 1}]},
                "recipients__0__\\ud800",
            ),
            (
                "recipient_message_data_with_template_key",
                "code",
                {"recipients": [{**RECIPIENT, "message_data": {"n": 1}}]},
                "recipients",
            ),
            (
                "key_of_a_refused_address_repeated",
                "template",
                {
                    "recipients": [
                        {"to": "not an address", "idempotency_key": "7"},
                        {**RECIPIENT, "idempotency_key": "7"},
                    ]
                },
                "recipients__1__idempotency_key",
            ),
            ("shared_data_over_256_kib", "template", {"message_data": {"blob": "x" * 256 * 1024}}, None),
            ("shared_content_over_256_kib", "code", {"html": "<p>" + "x" * 256 * 1024 + "</p>"}, None),
        ]
    )
    def test_refuses_a_batch_it_cannot_send_as_a_whole(self, mock_post, _flag, _capture, _name, form, fields, attr):
        response = self._batch(form, **fields)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == attr
        mock_post.assert_not_called()

    def test_refuses_a_body_over_5_mib_before_parsing_it(self, mock_post, _flag, capture):
        analytics = FakeAnalytics()
        capture.side_effect = analytics.capture

        response = self._batch("template", message_data={"blob": "x" * 5 * 1024 * 1024})

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, response.json()
        assert response.json()["code"] == "content_too_large"
        (refused,) = analytics.properties_of(SEND_EVENT)
        assert (refused["outcome"], refused["attachment_count"], refused["attachment_bytes"]) == (
            "rejected",
            None,
            None,
        )
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("the_most_recipients_a_batch_takes", 100, "application/json", None),
            ("a_json_media_type_in_any_case", 2, "Application/JSON; charset=utf-8", None),
            ("half_an_emoji_in_a_recipients_data", 2, "application/json", '"\\ud83d"'),
        ]
    )
    def test_queues_every_recipient_of_a_json_batch(
        self, mock_post, _flag, _capture, _name, count, content_type, first_name_json
    ):
        mock_post.return_value = self._queued_answer(count)
        recipients = self._recipients(count)
        if first_name_json is not None:
            recipients[0]["message_data"] = {"name": "first-name"}
        body = json.dumps({**self._email("template"), "recipients": recipients})
        if first_name_json is not None:
            body = body.replace('"first-name"', first_name_json)

        response = self.psak.post(BATCH_URL, body, content_type=content_type)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [(result["message_id"], result["status"]) for result in response.json()["results"]] == [
            (self._id(f"key-{index}"), "queued") for index in range(count)
        ]
        (forward,) = mock_post.call_args_list
        assert len(_forwarded(forward)["recipients"]) == count

    @parameterized.expand(
        [("text_plain", "text/plain"), ("any_type", "*/*"), ("any_application_type", "application/*")]
    )
    def test_refuses_a_batch_body_not_labelled_json(self, mock_post, _flag, _capture, _name, content_type):
        mock_post.return_value = self._queued_answer(1)
        body = {**self._email("template"), "recipients": self._recipients(1)}

        response = self.psak.post(BATCH_URL, json.dumps(body), content_type=content_type)

        assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, response.json()
        mock_post.assert_not_called()

    def test_a_duplicate_key_names_both_recipients(self, mock_post, _flag, _capture):
        recipients = [{**RECIPIENT, "to": "a@example.com"}, {**RECIPIENT, "to": "b@example.com"}]

        response = self._batch("template", recipients)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "recipients__1__idempotency_key"
        assert "Recipient 0" in response.json()["detail"]

    @parameterized.expand([("template",), ("code",)])
    def test_a_disabled_workflow_still_forwards_and_the_pipeline_refuses_the_whole_batch(
        self, mock_post, _flag, _capture, form
    ):
        if form == "code":
            mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "single"})
            assert self._single("code").status_code == status.HTTP_202_ACCEPTED
            hog_flow_id = TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).get().hog_flow_id
            mock_post.reset_mock()
        else:
            hog_flow_id = self.hog_flow_id
        self._archive(hog_flow_id)
        mock_post.return_value = _response(400, {"error": "not_sendable"})

        response = self._batch(form, self._recipients(2))

        assert (response.status_code, response.json()["code"]) == (400, "transactional_email_paused")
        (forward,) = mock_post.call_args_list
        assert forward.args[0].endswith(f"/hog_flows/{hog_flow_id}{BATCH_WIRE[form][0]}")

    def test_a_template_made_with_the_key_during_a_first_code_batch_answers_as_a_single_code_send_does(
        self, mock_post, _flag, _capture
    ):
        lock = transactional_email._lock_team_keys

        def lock_then_an_import_makes_the_template(team_id: int) -> None:
            lock(team_id)
            MessageTemplate.objects.create(team_id=team_id, key="welcome", name="Imported", type="email", content={})

        with patch.object(transactional_email, "_lock_team_keys", side_effect=lock_then_an_import_makes_the_template):
            single = self._single("code")
            MessageTemplate.objects.filter(team_id=self.team.id, key="welcome").delete()
            response = self._batch("code")

        assert single.json()["code"] == "template_not_transactional"
        assert (response.status_code, response.json()) == (single.status_code, single.json())
        mock_post.assert_not_called()

    @parameterized.expand(WHOLE_CALL_REFUSALS)
    def test_a_whole_call_refusal_answers_as_a_single_send_does(
        self, mock_post, _flag, capture, pipeline_code, pipeline_status, public_code, public_status, as_single_send
    ):
        mock_post.return_value = _response(pipeline_status, {"error": pipeline_code})
        single = self._single("code")
        analytics = FakeAnalytics()
        capture.side_effect = analytics.capture

        response = self._batch("code")

        assert (response.status_code, response.json()["code"]) == (public_status, public_code)
        assert "results" not in response.json()
        assert (response.json() == single.json()) == as_single_send
        if pipeline_code == "sandbox_fields_unsupported":
            assert "PostHog test sender" in response.json()["detail"]
        assert [(event["outcome"], event["error_code"]) for event in analytics.properties_of(SEND_EVENT)] == [
            ("rejected", public_code)
        ]

    def test_a_suppressed_or_unreachable_recipient_answers_what_a_single_send_to_it_answers(
        self, mock_post, _flag, _capture
    ):
        single_answers = {}
        for code in ("recipient_suppressed", "recipient_unreachable"):
            mock_post.return_value = _response(422, {"error": code, "invocation_id": self._id("key-0")})
            single = self._single()
            single_answers[code] = {
                "code": single.json()["code"],
                "status": single.status_code,
                "detail": single.json()["detail"],
            }
        mock_post.return_value = _batch_answer(
            _accepted(self._id("key-0")),
            {"status": 422, "body": {"error": "recipient_suppressed", "invocation_id": self._id("key-1")}},
            {"status": 422, "body": {"error": "recipient_unreachable", "invocation_id": self._id("key-2")}},
        )

        response = self._batch("template", self._recipients(3))

        assert response.status_code == status.HTTP_200_OK, response.json()
        queued, suppressed, unreachable = response.json()["results"]
        assert queued == {"message_id": self._id("key-0"), "status": "queued", "replayed": False}
        assert [suppressed["message_id"], unreachable["message_id"]] == [self._id("key-1"), self._id("key-2")]
        for result, code in ((suppressed, "recipient_suppressed"), (unreachable, "recipient_unreachable")):
            assert {name: result["error"][name] for name in ("code", "status", "detail")} == single_answers[code]
            assert result["error"]["retryable"] is False

    @parameterized.expand(RECIPIENT_REFUSALS)
    def test_each_recipient_refusal_maps_to_its_public_code_and_keeps_its_message_id(
        self, mock_post, _flag, _capture, pipeline_code, pipeline_status, public_code, public_status
    ):
        refusal = {"error": pipeline_code, "invocation_id": self._id("key-1")}
        mock_post.return_value = _batch_answer(
            _accepted(self._id("key-0")), {"status": pipeline_status, "body": refusal}
        )

        response = self._batch("template", self._recipients(2))

        assert response.status_code == status.HTTP_200_OK, response.json()
        queued, refused = response.json()["results"]
        assert queued == {"message_id": self._id("key-0"), "status": "queued", "replayed": False}
        assert refused["message_id"] == self._id("key-1")
        assert {name: refused["error"][name] for name in ("code", "status", "retryable")} == {
            "code": public_code,
            "status": public_status,
            "retryable": public_code == "delivery_unavailable",
        }
        if public_code == "delivery_unavailable":
            assert "same `idempotency_key`" in refused["error"]["detail"]
            assert "24 hours" in refused["error"]["detail"]

    @parameterized.expand(
        [
            ("pod_without_batch_routes", {"return_value": _response(401, {"error": "Unauthorized"})}),
            ("a_failed_lookup", {"return_value": _response(500, {"error": "lookup failed"})}),
            ("a_missed_deadline", {"return_value": _response(503, {"error": "deadline_exceeded"})}),
            ("timeout", {"side_effect": requests.ReadTimeout()}),
            ("an_answer_missing", lambda ids: [_accepted(ids[0])]),
            ("an_answer_without_a_status", lambda ids: [_accepted(ids[0]), {"body": {}}]),
            ("a_missing_team", {"return_value": _response(404, {"error": "Team not found"})}),
            ("a_pipeline_at_capacity", {"return_value": _response(503, {"error": "over_capacity"})}),
        ]
    )
    def test_a_batch_the_pipeline_does_not_answer_in_full_is_unavailable(
        self, mock_post, _flag, capture, _name, answer
    ):
        analytics = FakeAnalytics()
        capture.side_effect = analytics.capture
        if callable(answer):
            mock_post.return_value = _batch_answer(*answer([self._id("key-0"), self._id("key-1")]))
        else:
            mock_post.configure_mock(**answer)

        response = self._batch("code")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.json()
        assert response.json()["code"] == "delivery_unavailable"
        assert "may still go out" in response.json()["detail"]
        assert [event["outcome"] for event in analytics.properties_of(SEND_EVENT)] == ["unavailable"]

    def test_the_rate_limit_is_reserved_before_the_key_is_created(self, mock_post, _flag, _capture):
        mock_post.return_value = self._queued_answer(5)

        with self._enforce_rate_limits(), patch.object(TransactionalEmailTeamBurstThrottle, "rate", "4/minute"):
            response = self._batch("code", self._recipients(5))

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert int(response.headers["Retry-After"]) > 0
        assert not TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).exists()
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            (f"{name}_{layout}", throttle, layout)
            for name, throttle in [
                ("key_burst", TransactionalEmailBurstThrottle),
                ("key_sustained", TransactionalEmailSustainedThrottle),
                ("team_burst", TransactionalEmailTeamBurstThrottle),
                ("team_sustained", TransactionalEmailTeamSustainedThrottle),
            ]
            for layout in ("configured_caches", "own_history_prefix")
        ]
    )
    def test_a_batch_spends_one_send_per_recipient_and_a_refused_one_spends_one(
        self, mock_post, _flag, _capture, _name, throttle, layout
    ):
        own_history_prefix = layout == "own_history_prefix"
        caches_under_test = (
            lagging_reader_caches(unique_key_prefix("test-batch-throttle")) if own_history_prefix else settings.CACHES
        )
        with (
            override_settings(CACHES=caches_under_test),
            self._enforce_rate_limits(),
            patch.object(throttle, "rate", "5/minute"),
        ):
            try:
                mock_post.return_value = self._queued_answer(3)
                spent = self._batch("template", self._recipients(3))
                refused = self._batch("template", self._recipients(3))
                mock_post.return_value = MagicMock(status_code=202, json=lambda: {"invocation_id": "single"})
                last_single = self._single("template")
                over_budget = self._single("template")
            finally:
                if own_history_prefix:
                    for alias in ("default", "throttle_history"):
                        redis_cache = caches[alias]
                        assert isinstance(redis_cache, RedisCache)
                        redis_cache.delete_pattern("*")

        assert spent.status_code == status.HTTP_200_OK, spent.json()
        assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert int(refused.headers["Retry-After"]) > 0
        assert last_single.status_code == status.HTTP_202_ACCEPTED, last_single.json()
        assert over_budget.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    @parameterized.expand(
        [
            ("from", {"from": "Example <hello@example.org>"}),
            ("reply_to", {"reply_to": ["help@example.org"]}),
            ("both", {"from": "Example <hello@example.org>", "reply_to": ["help@example.org"]}),
        ]
    )
    def test_a_sandbox_batch_that_names_a_sender_answers_as_a_single_send_does(
        self, mock_post, _flag, _capture, _name, sender
    ):
        Integration.objects.filter(id=self.sender.id).delete()
        TeamWorkflowsConfig.objects.filter(team_id=self.team.id).update(default_email_integration_id=None)
        sandbox_send = {"invocation_id": self._id("key-0"), "replayed": False, "sender_kind": "email_sandbox"}
        mock_post.return_value = MagicMock(status_code=202, json=lambda: sandbox_send)
        single = self._single("code", **sender)
        single_send = _forwarded(mock_post.call_args)["send"] if mock_post.called else None
        mock_post.reset_mock()
        mock_post.return_value = _batch_answer(
            *(_accepted(self._id(key), sender_kind="email_sandbox") for key in ("key-0", "key-1"))
        )

        batch = self._batch("code", **sender)

        if single.status_code == status.HTTP_202_ACCEPTED:
            assert batch.status_code == status.HTTP_200_OK, batch.json()
            assert batch.json()["warnings"] == [
                {**warning, "message": warning["message"].replace(SANDBOX_SENDER_WARNING, BATCH_SANDBOX_SENDER_WARNING)}
                for warning in single.json()["warnings"]
            ]
            (batch_call,) = mock_post.call_args_list
            assert _forwarded(batch_call)["send"] == single_send
        else:
            assert (batch.status_code, batch.json()) == (single.status_code, single.json())

    @parameterized.expand(
        [
            ("every_recipient_from_the_sandbox_sender", "template", "email_sandbox", "email_sandbox", True),
            ("only_a_replay_from_the_sandbox_sender", "code", None, "email_sandbox", True),
            ("every_recipient_from_its_own_sender", "template", None, None, False),
        ]
    )
    def test_warns_once_when_any_queued_recipient_went_out_from_the_sandbox_sender(
        self, mock_post, _flag, _capture, _name, form, queued_sender_kind, replayed_sender_kind, warns
    ):
        mock_post.return_value = _batch_answer(
            _accepted(self._id("key-0"), **_sent_by(queued_sender_kind)),
            _accepted(self._id("key-1"), replayed=True, **_sent_by(replayed_sender_kind)),
            {"status": 422, "body": {"error": "sandbox_recipient_not_member"}},
        )

        response = self._batch(form, self._recipients(3))

        assert response.status_code == status.HTTP_200_OK, response.json()
        warnings = response.json().get("warnings", [])
        assert [(warning["code"], warning["message"]) for warning in warnings] == (
            [("sandbox_sender", BATCH_SANDBOX_SENDER_WARNING)] if warns else []
        )

    @parameterized.expand(
        [
            ("batch_flag_off", "template", {TRANSACTIONAL_EMAIL_API_FLAG, EMAIL_FROM_CODE_FLAG}, "application/json"),
            ("batch_flag_off_any_type", "template", {TRANSACTIONAL_EMAIL_API_FLAG, EMAIL_FROM_CODE_FLAG}, "*/*"),
            (
                "batch_flag_off_any_application_type",
                "template",
                {TRANSACTIONAL_EMAIL_API_FLAG, EMAIL_FROM_CODE_FLAG},
                "application/*",
            ),
            ("template_flag_off", "template", {EMAIL_BATCH_FLAG, EMAIL_FROM_CODE_FLAG}, "application/json"),
            ("code_flag_off", "code", {EMAIL_BATCH_FLAG, TRANSACTIONAL_EMAIL_API_FLAG}, "application/json"),
        ]
    )
    def test_is_hidden_while_a_flag_it_needs_is_off(
        self, mock_post, flag, _capture, _name, form, enabled_flags, content_type
    ):
        flag.side_effect = lambda key, *_args, **_kwargs: key in enabled_flags
        body = json.dumps({**self._email(form), "recipients": self._recipients(2)})

        with self._enforce_rate_limits(), patch.object(TransactionalEmailTeamBurstThrottle, "rate", "1/minute"):
            responses = [self.psak.post(BATCH_URL, body, content_type=content_type) for _ in range(2)]

        assert [response.status_code for response in responses] == [status.HTTP_404_NOT_FOUND] * 2
        mock_post.assert_not_called()
