import json
from collections.abc import Iterator

import pytest
from unittest.mock import patch

from django.test.client import Client as HttpClient

import requests
import responses
import posthoganalytics
from rest_framework import status

from posthog.integrations import IntegrationManager
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

TWILIO_SID = "AC" + "0" * 32
TWILIO_401 = {"code": 20003, "message": "Authenticate", "status": 401}
CAPTURE_HOST = "https://capture.example.com"


def exceptions_reported(http: responses.RequestsMock) -> int:
    return sum(
        event["event"] == "$exception"
        for call in http.calls
        if call.request.url == f"{CAPTURE_HOST}/batch/"
        for event in json.loads(call.request.body)["batch"]
    )


class TestTwilioIntegration:
    @pytest.fixture(autouse=True)
    def setup_integration(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "test@posthog.com", "test")

    @pytest.fixture
    def http(self) -> Iterator[responses.RequestsMock]:
        with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
            mock.post(f"{CAPTURE_HOST}/batch/", json={"status": 1})
            reporter = posthoganalytics.Client("phc_test", host=CAPTURE_HOST, sync_mode=True)
            with patch.multiple(posthoganalytics, default_client=reporter, disabled=False):
                yield mock

    @pytest.mark.parametrize(
        "typed_sid,typed_token",
        [
            pytest.param(TWILIO_SID, "fake-token", id="as_typed"),
            pytest.param(f" {TWILIO_SID}\n", " fake-token\n", id="pasted_with_whitespace"),
        ],
    )
    def test_create_stores_the_account_that_twilio_confirms(
        self, typed_sid: str, typed_token: str, client: HttpClient, http: responses.RequestsMock
    ):
        twilio_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}.json"
        http.get(twilio_url, json={"sid": TWILIO_SID})
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.pk}/integrations/",
            {"kind": "twilio", "config": {"account_sid": typed_sid, "auth_token": typed_token}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        (twilio_call,) = [call for call in http.calls if call.request.url == twilio_url]
        assert twilio_call.request.headers["Authorization"] == requests.auth._basic_auth_str(TWILIO_SID, "fake-token")
        row = IntegrationManager.twilio.token.get(self.team.id, response.json()["id"])
        assert (row.integration_id, row.created_by_id, dict(row.sensitive_config)) == (
            TWILIO_SID,
            self.user.id,
            {"auth_token": "fake-token"},
        )
        assert response.json()["created_by"]["id"] == self.user.id

    @pytest.mark.parametrize(
        "account_sid,auth_token,attr,detail",
        [
            pytest.param(
                "someone@example.com",
                "wrong-token",
                "account_sid",
                "This is not an account SID. Account SIDs start with AC and are 34 characters long. Copy yours from the Twilio Console.",
                id="not_an_account_sid",
            ),
            pytest.param(
                TWILIO_SID,
                " \n",
                "auth_token",
                "Enter your auth token. Copy it from the Twilio Console.",
                id="blank_auth_token",
            ),
            pytest.param(
                TWILIO_SID,
                "wrong-token",
                None,
                "Twilio rejected these credentials. Check your account SID and auth token.",
                id="rejected_by_twilio",
            ),
        ],
    )
    def test_create_with_bad_credentials_tells_the_user_and_reports_nothing(
        self,
        account_sid: str,
        auth_token: str,
        attr: str | None,
        detail: str,
        client: HttpClient,
        http: responses.RequestsMock,
    ):
        http.get(f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}.json", status=401, json=TWILIO_401)
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.pk}/integrations/",
            {"kind": "twilio", "config": {"account_sid": account_sid, "auth_token": auth_token}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert (response.json()["attr"], response.json()["detail"]) == (attr, detail)
        assert not Integration.objects.filter(team=self.team, kind="twilio").exists()
        assert exceptions_reported(http) == 0

    @pytest.mark.parametrize(
        "twilio_status,twilio_body,expected_status,expected_body,expected_reports",
        [
            pytest.param(200, {"incoming_phone_numbers": []}, 200, {"phone_numbers": []}, 0, id="no_numbers"),
            pytest.param(
                401,
                TWILIO_401,
                400,
                {
                    "detail": "Twilio rejected the saved credentials. "
                    "In Channels, add Twilio again with the same account SID and your current auth token."
                },
                0,
                id="rejected_by_twilio",
            ),
            pytest.param(500, {"code": 20500}, 500, {"type": "server_error"}, 1, id="twilio_failing"),
        ],
    )
    def test_phone_numbers_answer_for_what_twilio_returned(
        self,
        twilio_status: int,
        twilio_body: dict,
        expected_status: int,
        expected_body: dict,
        expected_reports: int,
        http: responses.RequestsMock,
    ):
        http.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/IncomingPhoneNumbers.json",
            status=twilio_status,
            json=twilio_body,
        )
        integration = Integration.objects.create(
            team=self.team,
            kind="twilio",
            integration_id=TWILIO_SID,
            config={"account_sid": TWILIO_SID},
            sensitive_config={"auth_token": "rotated-token"},
        )
        client = HttpClient(raise_request_exception=False)
        client.force_login(self.user)

        response = client.get(
            f"/api/projects/{self.team.pk}/integrations/{integration.id}/twilio_phone_numbers?force_refresh=true"
        )

        assert response.status_code == expected_status, response.content
        assert expected_body.items() <= response.json().items()
        assert exceptions_reported(http) == expected_reports
