from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.integration import Integration

from products.access_control.backend.facade.testing import PropertyAccess, set_member_property_access
from products.access_control.backend.models.access_control import AccessControl
from products.messaging.backend.facade.provider_imports import ProviderImportRejected
from products.messaging.backend.models.provider_import_run import ProviderImportRun
from products.messaging.backend.services.customerio_client import CustomerIOAPIError


@patch("products.messaging.backend.provider_imports.runs.start_provider_import_workflow")
@patch("products.messaging.backend.services.customerio_import_service.CustomerIOClient")
class TestProviderImportsAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/messaging_provider_imports/"

    def test_start_runs_the_selected_steps_in_provider_order(
        self, _mock_client_class: MagicMock, start_workflow: MagicMock
    ) -> None:
        response = self.client.post(
            self._url(), {"provider": "customerio", "steps": ["opt_outs", "suppressions"], "api_key": "app-key"}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["status"] == "queued"
        assert [step["key"] for step in response.json()["steps"]] == ["suppressions", "opt_outs"]
        start_workflow.assert_called_once()
        assert start_workflow.call_args.kwargs["steps"] == ["suppressions", "opt_outs"]
        assert Integration.objects.get(team_id=self.team.id, kind="customerio-app").sensitive_config == {
            "app_api_key": "app-key"
        }
        assert self.client.get(f"{self._url()}{response.json()['id']}/").json()["id"] == response.json()["id"]

    def test_rejects_a_second_import_while_one_is_running(
        self, _mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        body = {"provider": "customerio", "steps": ["suppressions"]}
        assert self.client.post(self._url(), {**body, "api_key": "app-key"}).status_code == status.HTTP_201_CREATED

        response = self.client.post(self._url(), body)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already running" in response.json()["detail"]

    @parameterized.expand(
        [
            ("without_cohort_write", ["hog_flow:write", "person:read"], ["automations"], 403),
            ("with_cohort_write", ["hog_flow:write", "person:read", "cohort:write"], ["automations"], 400),
            ("full_access_key", ["*"], ["automations"], 400),
            ("other_steps_need_no_cohort_write", ["hog_flow:write", "person:read"], ["templates"], 400),
            ("contacts_without_person_write", ["hog_flow:write", "person:read", "cohort:write"], ["contacts"], 403),
            ("new_people_without_cohort_write", ["hog_flow:write", "person:write"], ["new_people"], 403),
            ("contacts_with_both", ["hog_flow:write", "cohort:write", "person:write"], ["contacts"], 400),
        ]
    )
    def test_steps_that_write_beyond_workflows_need_those_scopes_on_a_key(
        self,
        _mock_client_class: MagicMock,
        start_workflow: MagicMock,
        _name: str,
        scopes: list[str],
        steps: list[str],
        expected: int,
    ) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response = self.client.post(
            self._url(),
            {"provider": "resend", "steps": steps, "api_key": "re_key"},
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

        assert response.status_code == expected, response.json()
        start_workflow.assert_not_called()

    @parameterized.expand(
        [
            ("restricted_automations", "restricted", "automations", 403),
            ("granted_automations", "granted", "automations", 400),
            ("restricted_suppressions", "restricted", "suppressions", 400),
        ]
    )
    def test_importing_automations_follows_property_access(
        self,
        _mock_client_class: MagicMock,
        start_workflow: MagicMock,
        _name: str,
        access: PropertyAccess,
        step: str,
        expected: int,
    ) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

        response = self.client.post(self._url(), {"provider": "resend", "steps": [step], "api_key": "re_key"})

        assert response.status_code == expected, response.json()
        start_workflow.assert_not_called()

    @parameterized.expand([("person_viewer", "viewer", 403), ("person_editor", "editor", 400)])
    def test_importing_contacts_needs_person_edit_access(
        self,
        _mock_client_class: MagicMock,
        start_workflow: MagicMock,
        _name: str,
        person_access: str,
        expected: int,
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(team=self.team, resource="person", resource_id=None, access_level=person_access)

        response = self.client.post(self._url(), {"provider": "resend", "steps": ["contacts"], "api_key": "re_key"})

        assert response.status_code == expected, response.json()
        start_workflow.assert_not_called()

    def test_lists_a_run_whose_provider_this_deploy_does_not_know(
        self, _mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        ProviderImportRun.objects.for_team(self.team.id).create(
            team=self.team, provider="retired", steps=["contacts"], status="completed"
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [step["key"] for step in response.json()[0]["steps"]] == ["contacts"]

    def test_the_list_leaves_out_items_that_getting_the_run_returns(
        self, _mock_client_class: MagicMock, _start_workflow: MagicMock
    ) -> None:
        items = [{"label": f"Template {i}", "status": "created", "url": None, "notes": ["Check it."]} for i in range(3)]
        run = ProviderImportRun.objects.for_team(self.team.id).create(
            team=self.team,
            provider="customerio",
            steps=["suppressions"],
            status="completed",
            progress={"suppressions": {"status": "completed", "items": items, "items_omitted": 7}},
        )

        listed = self.client.get(self._url()).json()[0]["steps"][0]
        detail = self.client.get(f"{self._url()}{run.id}/").json()["steps"][0]

        assert (listed["items"], listed["items_omitted"]) == ([], 10)
        assert ([item["label"] for item in detail["items"]], detail["items_omitted"]) == (
            ["Template 0", "Template 1", "Template 2"],
            7,
        )

    @parameterized.expand(
        [
            ("unknown_step", ["automations"], None, status.HTTP_400_BAD_REQUEST, "no step named automations"),
            (
                "rejected_key",
                ["suppressions"],
                401,
                status.HTTP_400_BAD_REQUEST,
                "Customer.io rejected the App API key",
            ),
            ("provider_down", ["suppressions"], 503, status.HTTP_503_SERVICE_UNAVAILABLE, "returned HTTP 503"),
        ]
    )
    def test_does_not_start_an_import_that_cannot_run(
        self,
        mock_client_class: MagicMock,
        start_workflow: MagicMock,
        _name: str,
        steps: list[str],
        topics_status: int | None,
        expected_status: int,
        expected_detail: str,
    ) -> None:
        if topics_status is not None:
            mock_client_class.return_value.get_subscription_topics.side_effect = CustomerIOAPIError(
                "Customer.io API error", status_code=topics_status
            )

        response = self.client.post(self._url(), {"provider": "customerio", "steps": steps, "api_key": "app-key"})

        assert response.status_code == expected_status, response.json()
        assert expected_detail in response.json()["detail"]
        start_workflow.assert_not_called()
        assert not Integration.objects.filter(team_id=self.team.id, kind="customerio-app").exists()

    @parameterized.expand(
        [
            ("providers", "providers/", ["hog_flow:read"], status.HTTP_200_OK),
            ("runs_need_person_read", "", ["hog_flow:read"], status.HTTP_403_FORBIDDEN),
            ("runs", "", ["hog_flow:read", "person:read"], status.HTTP_200_OK),
        ]
    )
    def test_reads_with_a_personal_api_key(
        self,
        _mock_client_class: MagicMock,
        _start_workflow: MagicMock,
        _name: str,
        path: str,
        scopes: list[str],
        expected: int,
    ) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response = self.client.get(f"{self._url()}{path}", HTTP_AUTHORIZATION=f"Bearer {key}")

        assert response.status_code == expected, response.json()

    def test_starting_an_import_with_a_key_needs_person_read(
        self, _mock_client_class: MagicMock, start_workflow: MagicMock
    ) -> None:
        key = self.create_personal_api_key_with_scopes(["hog_flow:write"])
        self.client.logout()

        response = self.client.post(
            self._url(),
            {"provider": "customerio", "steps": ["suppressions"], "api_key": "app-key"},
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        start_workflow.assert_not_called()


@patch("products.messaging.backend.facade.provider_imports.feature_enabled_or_false", return_value=False)
class TestProviderImportFlag(APIBaseTest):
    @parameterized.expand([("resend",), ("postmark",), ("mailchimp",)])
    def test_a_flagged_provider_stays_hidden_and_refused_while_its_flag_is_off(
        self, _flag: MagicMock, provider: str
    ) -> None:
        url = f"/api/projects/{self.team.id}/messaging_provider_imports/"

        providers = self.client.get(f"{url}providers/").json()
        response = self.client.post(url, {"provider": provider, "steps": ["suppressions"], "api_key": "a_key"})

        assert [provider["key"] for provider in providers] == ["customerio"]
        assert response.status_code == 400
        assert f"Unknown import provider: {provider}" in str(response.json())

    def test_mailgun_needs_its_flag_and_a_region(self, flag: MagicMock) -> None:
        url = f"/api/projects/{self.team.id}/messaging_provider_imports/"
        body = {"provider": "mailgun", "steps": ["bounces"], "api_key": "key"}
        flag.return_value = False
        assert "mailgun" not in [row["key"] for row in self.client.get(f"{url}providers/").json()]
        assert self.client.post(url, body).status_code == 400

        flag.return_value = True
        mailgun = next(row for row in self.client.get(f"{url}providers/").json() if row["key"] == "mailgun")
        response = self.client.post(url, body)

        assert [setting["key"] for setting in mailgun["settings"]] == ["region", "template_versions"]
        assert any("names on the email preferences page" in step for step in mailgun["next_steps"])
        assert response.status_code == 400
        assert "Mailgun region" in response.json()["detail"]

    def test_mailgun_contacts_need_their_own_flag(self, flag: MagicMock) -> None:
        flag.side_effect = lambda key, *_args, **_kwargs: key == "workflows-mailgun-import"
        url = f"/api/projects/{self.team.id}/messaging_provider_imports/"

        [mailgun] = [row for row in self.client.get(f"{url}providers/").json() if row["key"] == "mailgun"]
        response = self.client.post(
            url,
            {
                "provider": "mailgun",
                "steps": ["bounces", "complaints", "unsubscribes", "mailing_lists", "contacts"],
                "settings": {"region": "us"},
                "api_key": "key",
            },
        )

        assert not {"contacts", "new_people"} & {step["key"] for step in mailgun["steps"]}
        assert response.status_code == 400
        assert "no step named contacts" in response.json()["detail"]

    @parameterized.expand([("contacts_off", False), ("contacts_on", True)])
    @patch("products.messaging.backend.presentation.views.provider_imports.start_provider_import")
    def test_a_flagged_step_stays_hidden_and_refused_while_its_flag_is_off(
        self, _name: str, contacts_on: bool, start: MagicMock, flag: MagicMock
    ) -> None:
        flag.side_effect = lambda key, *_args, **_kwargs: contacts_on or key == "workflows-sendgrid-import"
        start.side_effect = ProviderImportRejected("started")
        url = f"/api/projects/{self.team.id}/messaging_provider_imports/"

        sendgrid = next(row for row in self.client.get(f"{url}providers/").json() if row["key"] == "sendgrid")
        body = {"provider": "sendgrid", "steps": ["suppressions", "contacts"], "api_key": "a_key"}
        response = self.client.post(url, body)

        assert ("contacts" in [step["key"] for step in sendgrid["steps"]]) == contacts_on
        assert ("Contacts don't become people" in sendgrid["not_imported"]) != contacts_on
        assert response.status_code == 400
        assert response.json()["detail"] == ("started" if contacts_on else "SendGrid has no step named contacts.")
