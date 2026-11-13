import json
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, ProjectSecretAPIKey, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.access_control.backend.facade.testing import create_access_control
from products.messaging.backend.presentation.views.attachment_uploads import (
    AttachmentUploadBurstThrottle,
    AttachmentUploadsRequestSerializer,
    AttachmentUploadTeamBurstThrottle,
)
from products.messaging.backend.presentation.views.transactional_email_access import (
    TransactionalEmailBurstThrottle,
    TransactionalEmailTeamBurstThrottle,
)

INVOICE = "a" * 64
LOGO = "b" * 64
PRESENT_LOGO = {"sha256": LOGO, "status": "present", "expires_at": "2026-12-01T09:00:00Z"}
UPLOAD_INVOICE = {
    "sha256": INVOICE,
    "status": "upload",
    "url": "https://attachments.example.com/team/1/" + INVOICE,
    "method": "PUT",
    "headers": {"Content-Length": "2000", "x-amz-checksum-sha256": "qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqo="},
    "url_expires_at": "2026-11-09T10:15:00Z",
}
TWO_FILES = {"files": [{"sha256": INVOICE, "size": 2000}, {"sha256": LOGO, "size": 300}]}


def _cdp_answers(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"return_value": MagicMock(status_code=status_code, json=lambda: body)}


@patch("products.messaging.backend.presentation.views.message_templates.posthoganalytics.capture")
@patch(
    "products.messaging.backend.presentation.views.transactional_email_access.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("posthog.plugins.plugin_server_api.internal_requests.post")
class TestAttachmentUploads(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/environments/{self.team.id}/messaging/attachments/uploads/"

    def _psak_client(self, scopes: list[str]) -> APIClient:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="uploads",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        return client

    def _upload(self, body: Any, scopes: tuple[str, ...] = ("transactional_email:write",)) -> Any:
        return self._psak_client(list(scopes)).post(self.url, body, format="json")

    @staticmethod
    def _reported(capture: MagicMock) -> list[dict[str, Any]]:
        return [
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs.get("event") == "transactional email attachments upload"
        ]

    def test_answers_each_file_as_present_or_with_where_to_put_it(self, mock_post, _flag, capture):
        mock_post.configure_mock(**_cdp_answers(200, {"files": [UPLOAD_INVOICE, PRESENT_LOGO]}))

        response = self._upload(TWO_FILES)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"files": [UPLOAD_INVOICE, PRESENT_LOGO]}
        url, kwargs = mock_post.call_args.args[0], mock_post.call_args.kwargs
        assert url.endswith(f"/api/projects/{self.team.id}/transactional_email/attachments/uploads")
        assert json.loads(kwargs["data"]) == TWO_FILES
        assert [
            {
                key: properties[key]
                for key in ("outcome", "file_count", "requested_bytes", "upload_bytes", "present_bytes")
            }
            for properties in self._reported(capture)
        ] == [
            {
                "outcome": "answered",
                "file_count": 2,
                "requested_bytes": 2300,
                "upload_bytes": 2000,
                "present_bytes": 300,
            }
        ]

    @parameterized.expand(
        [
            (
                "team_not_on_the_allowlist",
                _cdp_answers(400, {"error": "field_not_accepted"}),
                400,
                "field_not_accepted",
                "files",
            ),
            (
                "too_large_for_any_message",
                _cdp_answers(400, {"error": "message_too_large", "sha256": LOGO}),
                400,
                "message_too_large",
                "files__1__size",
            ),
            (
                "over_the_daily_upload_cap",
                _cdp_answers(429, {"error": "upload_quota_exceeded"}),
                429,
                "upload_quota_exceeded",
                None,
            ),
            (
                "a_file_list_the_pipeline_finds_invalid",
                _cdp_answers(400, {"error": "invalid_request", "detail": "One sha256 is listed with two sizes"}),
                400,
                "invalid_request",
                "files",
            ),
            ("storage_down", _cdp_answers(503, {"error": "delivery_unavailable"}), 503, "delivery_unavailable", None),
            ("pipeline_unreachable", {"side_effect": requests.ConnectTimeout()}, 503, "delivery_unavailable", None),
            (
                "an_answer_missing_fields",
                _cdp_answers(200, {"files": [{"sha256": INVOICE, "status": "upload"}, PRESENT_LOGO]}),
                503,
                "delivery_unavailable",
                None,
            ),
            (
                "an_answer_with_an_unknown_status",
                _cdp_answers(200, {"files": [{**UPLOAD_INVOICE, "status": "pending"}, PRESENT_LOGO]}),
                503,
                "delivery_unavailable",
                None,
            ),
            (
                "an_answer_with_headers_that_are_not_an_object",
                _cdp_answers(200, {"files": [{**UPLOAD_INVOICE, "headers": []}, PRESENT_LOGO]}),
                503,
                "delivery_unavailable",
                None,
            ),
            (
                "an_answer_without_an_upload_url",
                _cdp_answers(200, {"files": [{**UPLOAD_INVOICE, "url": None}, PRESENT_LOGO]}),
                503,
                "delivery_unavailable",
                None,
            ),
            (
                "an_answer_for_other_files",
                _cdp_answers(200, {"files": [PRESENT_LOGO, UPLOAD_INVOICE]}),
                503,
                "delivery_unavailable",
                None,
            ),
        ]
    )
    def test_refuses_what_the_pipeline_refuses_with_a_reason_and_a_fix(
        self, mock_post, _flag, capture, _name, pipeline, expected_status, code, attr
    ):
        mock_post.configure_mock(**pipeline)

        response = self._upload(TWO_FILES)

        assert response.status_code == expected_status, response.json()
        body = response.json()
        assert (body["code"], body["attr"]) == (code, attr)
        assert body["why"] and body["fix"]
        assert [
            (properties["outcome"], properties["error_code"], properties["file_count"], properties["requested_bytes"])
            for properties in self._reported(capture)
        ] == [("unavailable" if expected_status == 503 else "rejected", code, 2, 2300)]

    @parameterized.expand(
        [
            (
                "more_than_ten_files",
                {"files": [{"sha256": INVOICE, "size": 1}] * 11},
                "too_many_attachments",
                "files",
                11,
                11,
                "at most 10 files",
            ),
            (
                "an_unknown_field",
                {"files": [{"sha256": INVOICE, "size": 1, "name": "a.pdf"}]},
                "invalid_request",
                "files__0__name",
                1,
                1,
                "Send each file as `{sha256, size}`.",
            ),
            (
                "one_hash_with_two_sizes",
                {"files": [{"sha256": INVOICE, "size": 1}, {"sha256": INVOICE, "size": 2}]},
                "invalid_request",
                "files__1__size",
                2,
                3,
                "list the file once",
            ),
            (
                "a_list_instead_of_an_object",
                [{"sha256": INVOICE, "size": 1}],
                "invalid_request",
                None,
                None,
                None,
                '`{"files": ',
            ),
        ]
    )
    def test_refuses_a_malformed_request_before_asking_the_pipeline(
        self, mock_post, _flag, capture, _name, body, code, attr, file_count, requested_bytes, fix
    ):
        response = self._upload(body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        refusal = response.json()
        assert (refusal["type"], refusal["code"], refusal["attr"]) == ("invalid_request", code, attr)
        assert refusal["why"] and fix in refusal["fix"]
        mock_post.assert_not_called()
        assert [
            (properties["outcome"], properties["error_code"], properties["file_count"], properties["requested_bytes"])
            for properties in self._reported(capture)
        ] == [("rejected", code, file_count, requested_bytes)]

    @parameterized.expand([("project_secret_api_key",), ("session",)])
    def test_limits_uploads_apart_from_sends(self, mock_post, _flag, _capture, auth):
        cache.clear()
        mock_post.configure_mock(**_cdp_answers(200, {"files": [UPLOAD_INVOICE, PRESENT_LOGO]}))
        client = self._psak_client(["transactional_email:write"]) if auth == "project_secret_api_key" else self.client

        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", new=lambda _ttl: True),
            patch.object(TransactionalEmailBurstThrottle, "rate", "0/minute"),
            patch.object(TransactionalEmailTeamBurstThrottle, "rate", "0/minute"),
            patch.object(AttachmentUploadBurstThrottle, "rate", "1/minute"),
            patch.object(AttachmentUploadTeamBurstThrottle, "rate", "1/minute"),
        ):
            statuses = [client.post(self.url, TWO_FILES, format="json").status_code for _ in range(2)]

        assert statuses == [status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS]

    def test_refuses_a_body_over_the_request_cap(self, mock_post, _flag, capture):
        response = self._upload({"files": [{"sha256": "a" * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1), "size": 1}]})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert (body["type"], body["code"]) == ("invalid_request", "content_too_large")
        assert body["why"] and body["fix"]
        mock_post.assert_not_called()
        assert [
            (properties["outcome"], properties["error_code"], properties["file_count"], properties["requested_bytes"])
            for properties in self._reported(capture)
        ] == [("rejected", "content_too_large", None, None)]

    @parameterized.expand(
        [
            ("a_key_without_the_send_scope", ("hog_flow:read",), True, status.HTTP_403_FORBIDDEN),
            ("a_key_with_the_workflows_scope", ("hog_flow:write",), True, status.HTTP_200_OK),
            ("while_sending_from_code_is_off", ("transactional_email:write",), False, status.HTTP_404_NOT_FOUND),
        ]
    )
    def test_takes_uploads_from_whoever_can_send_from_code(
        self, mock_post, flag, _capture, _name, scopes, flag_on, expected_status
    ):
        flag.return_value = flag_on
        mock_post.configure_mock(**_cdp_answers(200, {"files": [UPLOAD_INVOICE, PRESENT_LOGO]}))

        response = self._upload(TWO_FILES, scopes)

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("editor_access_to_one_workflow", {None: "viewer", "one-workflow": "editor"}, status.HTTP_200_OK),
            ("viewer_access_to_workflows", {None: "viewer"}, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_takes_uploads_from_a_member_who_can_send_through_some_workflow(
        self, mock_post, _flag, _capture, _name, levels, expected_status
    ):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "member@example.com", "testtest")
        membership_id = OrganizationMembership.objects.get(user=member, organization=self.organization).id
        for resource_id, access_level in levels.items():
            create_access_control(
                team_id=self.team.id,
                resource="hog_flow",
                resource_id=str(uuid4()) if resource_id else None,
                access_level=access_level,
                organization_member_id=membership_id,
            )
        self.client.force_login(member)
        mock_post.configure_mock(**_cdp_answers(200, {"files": [UPLOAD_INVOICE, PRESENT_LOGO]}))

        response = self.client.post(self.url, TWO_FILES, format="json")

        assert response.status_code == expected_status, response.json()


class TestAttachmentUploadsRequest(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_files", {"files": []}, ("files",), "min_length"),
            ("a_hash_that_is_not_hex", {"files": [{"sha256": "z" * 64, "size": 1}]}, ("files", 0, "sha256"), "invalid"),
            ("an_empty_file", {"files": [{"sha256": INVOICE, "size": 0}]}, ("files", 0, "size"), "min_value"),
            ("more_than_ten_empty_files", {"files": [{}] * 11}, ("files",), "max_length"),
        ]
    )
    def test_refuses_a_malformed_file_list(self, _name, body, path, code):
        serializer = AttachmentUploadsRequestSerializer(data=body)

        assert not serializer.is_valid()
        errors: Any = serializer.errors
        for key in path:
            errors = errors[key]
        assert errors[0].code == code
