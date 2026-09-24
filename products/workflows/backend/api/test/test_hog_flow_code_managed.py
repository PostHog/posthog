from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.workflows.backend.api.hog_flow import HogFlowViewSet
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule

TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}
EXIT_ACTION = {"id": "exit_node", "name": "exit", "type": "exit", "config": {}}


class TestCodeManagedHogFlow(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.workflow = self._create_workflow(managed_by=HogFlow.ManagedBy.CODE)

    def _create_workflow(self, managed_by: str | None, status_value: str = HogFlow.State.DRAFT) -> HogFlow:
        return HogFlow.objects.create(
            team=self.team,
            name="Welcome",
            status=status_value,
            managed_by=managed_by,
            actions=[TRIGGER_ACTION, EXIT_ACTION],
            edges=[{"from": "trigger_node", "to": "exit_node", "type": "continue"}],
            trigger=TRIGGER_ACTION["config"],
            source_repository="github.com/example/flows",
            source_path="workflows/welcome.ts",
            source_ref="0f1e2d3",
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/hog_flows/{self.workflow.id}{suffix}"

    def _api_key_client(self, scopes: list[str] | None = None):
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="push",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=scopes or ["hog_flow:write", "hog_flow:read"],
        )
        return self.client_class(), {"authorization": f"Bearer {key}"}

    @parameterized.expand(
        [
            ("update_content", "patch", "", {"actions": [TRIGGER_ACTION]}),
            ("update_name", "patch", "", {"name": "Renamed in the UI"}),
            ("update_description", "patch", "", {"description": "Edited in the UI"}),
            ("update_status_and_content", "patch", "", {"status": "active", "name": "Renamed"}),
            ("destroy", "delete", "", None),
            ("graph", "patch", "/graph", {"operations": [{"op": "remove_action", "id": "exit_node"}]}),
            ("action_email", "patch", "/actions/exit_node/email", {"email_patch": {"subject": "Hello"}}),
            ("publish", "post", "/publish", {}),
            ("discard_draft", "post", "/discard_draft", {}),
            ("restore_revision", "post", "/revisions/1/restore", {}),
        ]
    )
    def test_web_write_is_refused(self, _name: str, method: str, suffix: str, payload: dict | None) -> None:
        call = getattr(self.client, method)
        response = call(self._url(suffix), payload) if payload is not None else call(self._url(suffix))

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "immutable", response.json()
        self.workflow.refresh_from_db()
        assert self.workflow.name == "Welcome"

    def test_refusal_names_the_recorded_source_and_the_way_out(self) -> None:
        response = self.client.patch(self._url(), {"name": "Renamed in the UI"})

        body = response.json()
        assert response.status_code == status.HTTP_403_FORBIDDEN, body
        assert body["code"] == "immutable"
        assert set(body["extra"]) == {"why", "fix", "source_repository", "source_path"}
        assert body["extra"]["source_repository"] == "github.com/example/flows"
        assert body["extra"]["source_path"] == "workflows/welcome.ts"

    @parameterized.expand(
        [
            ("update", "patch", {"name": "Renamed in the UI"}),
            ("destroy", "delete", None),
        ]
    )
    def test_a_push_that_lands_mid_request_still_refuses_the_write(
        self, _name: str, method: str, payload: dict | None
    ) -> None:
        gui_workflow = self._create_workflow(managed_by=HogFlow.ManagedBy.GUI)
        original_get_object = HogFlowViewSet.get_object

        def get_object_then_push(viewset):
            hog_flow = original_get_object(viewset)
            HogFlow.objects.filter(pk=hog_flow.pk).update(managed_by=HogFlow.ManagedBy.CODE)
            return hog_flow

        call = getattr(self.client, method)
        url = f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}"
        with patch.object(HogFlowViewSet, "get_object", get_object_then_push):
            response = call(url, payload) if payload is not None else call(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "immutable", response.json()
        gui_workflow.refresh_from_db()
        assert gui_workflow.name == "Welcome"

    def test_a_status_write_racing_a_push_keeps_what_the_push_wrote(self) -> None:
        gui_workflow = self._create_workflow(managed_by=HogFlow.ManagedBy.GUI)
        pushed_trigger = {
            **TRIGGER_ACTION,
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}]},
            },
        }
        original_perform_update = HogFlowViewSet.perform_update

        def push_then_perform_update(viewset, serializer):
            HogFlow.objects.filter(pk=gui_workflow.pk).update(
                managed_by=HogFlow.ManagedBy.CODE,
                actions=[pushed_trigger, EXIT_ACTION],
                trigger=pushed_trigger["config"],
                source_ref="a1b2c3d",
            )
            return original_perform_update(viewset, serializer)

        with patch.object(HogFlowViewSet, "perform_update", push_then_perform_update):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}", {"status": HogFlow.State.ARCHIVED}
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["managed_by"] == HogFlow.ManagedBy.CODE
        gui_workflow.refresh_from_db()
        assert gui_workflow.status == HogFlow.State.ARCHIVED
        assert gui_workflow.managed_by == HogFlow.ManagedBy.CODE
        assert gui_workflow.source_ref == "a1b2c3d"
        assert gui_workflow.actions[0]["config"] == pushed_trigger["config"]
        assert gui_workflow.trigger == pushed_trigger["config"]

    def test_bulk_delete_is_refused(self) -> None:
        self.workflow.status = HogFlow.State.ARCHIVED
        self.workflow.save()
        gui_workflow = self._create_workflow(managed_by=None, status_value=HogFlow.State.ARCHIVED)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": [str(self.workflow.id), str(gui_workflow.id)]},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "immutable"
        assert HogFlow.objects.filter(id=gui_workflow.id).exists()
        assert HogFlow.objects.filter(id=self.workflow.id).exists()

    @parameterized.expand(
        [
            ("mcp_transport", {"x-posthog-client": "mcp"}, True),
            ("cli_consumer_over_mcp", {"x-posthog-client": "mcp", "x-posthog-mcp-consumer": "posthog-cli"}, True),
            ("cli_user_agent_from_the_browser", {"user-agent": "posthog-cli"}, False),
            ("cli_consumer_header_from_the_browser", {"x-posthog-mcp-consumer": "posthog-cli"}, False),
        ]
    )
    def test_agent_and_spoofed_cli_writes_are_refused(
        self, _name: str, headers: dict[str, str], with_api_key: bool
    ) -> None:
        if with_api_key:
            client, auth = self._api_key_client()
            response = client.patch(self._url(), {"name": "Renamed"}, headers={**auth, **headers})
        else:
            response = self.client.patch(self._url(), {"name": "Renamed"}, headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "immutable"

    @parameterized.expand(
        [
            ("cancel_invocations", "/invocations/cancel"),
            ("resume_email_sending", "/resume_email_sending"),
        ]
    )
    def test_operating_a_code_managed_workflow_is_not_refused(self, _name: str, suffix: str) -> None:
        response = self.client.post(self._url(suffix), {})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("code") != "immutable", response.json()

    def test_the_ui_sets_the_schedule_of_a_code_managed_workflow(self) -> None:
        starts_at = (timezone.now() + timedelta(days=1)).isoformat()

        response = self.client.post(self._url("/schedules"), {"rrule": "FREQ=DAILY", "starts_at": starts_at})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert HogFlowSchedule.objects.filter(hog_flow=self.workflow, rrule="FREQ=DAILY").exists()

    @parameterized.expand(
        [
            ("the_source", {"source_repository": "github.com/example/not-mine"}, "source_repository"),
            ("code_ownership", {"managed_by": "code"}, "managed_by"),
            ("code_ownership_in_a_form_body", {"managed_by": "code", "name": "Claimed"}, "managed_by"),
        ]
    )
    def test_a_web_request_cannot_claim(self, _name: str, payload: dict, field: str) -> None:
        gui_workflow = self._create_workflow(managed_by=None)
        gui_workflow.source_repository = None
        gui_workflow.save()

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}", payload)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "immutable", response.json()
        gui_workflow.refresh_from_db()
        assert getattr(gui_workflow, field) != payload[field]

    def test_created_via_is_stamped_from_the_request_and_not_from_the_payload(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "From the editor", "created_via": "cli", "actions": [TRIGGER_ACTION, EXIT_ACTION]},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert HogFlow.objects.get(id=response.json()["id"]).created_via == HogFlow.CreatedVia.WEB

    def test_api_key_push_still_writes_the_content(self) -> None:
        client, auth = self._api_key_client()

        response = client.patch(
            self._url(),
            {"name": "Renamed by the push", "description": "From the file"},
            headers=auth,
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.workflow.refresh_from_db()
        assert self.workflow.name == "Renamed by the push"
        assert self.workflow.managed_by == HogFlow.ManagedBy.CODE

    @parameterized.expand(
        [
            ("bare", False),
            ("with_concurrency_fence", True),
        ]
    )
    def test_status_only_write_still_works_from_the_web(self, _name: str, fenced: bool) -> None:
        extra = {"base_updated_at": self.workflow.updated_at.isoformat()} if fenced else {}
        response = self.client.patch(self._url(), {"status": "active", **extra})

        assert response.status_code == status.HTTP_200_OK, response.json()
        self.workflow.refresh_from_db()
        assert self.workflow.status == HogFlow.State.ACTIVE
        assert self.workflow.managed_by == HogFlow.ManagedBy.CODE

    def test_managed_by_alone_releases_the_workflow_and_a_mixed_payload_is_refused(self) -> None:
        mixed = self.client.patch(self._url(), {"managed_by": "gui", "name": "Renamed"})
        assert mixed.status_code == status.HTTP_403_FORBIDDEN, mixed.json()
        self.workflow.refresh_from_db()
        assert self.workflow.managed_by == HogFlow.ManagedBy.CODE

        released = self.client.patch(self._url(), {"managed_by": "gui"})
        assert released.status_code == status.HTTP_200_OK, released.json()
        self.workflow.refresh_from_db()
        assert self.workflow.managed_by == HogFlow.ManagedBy.GUI

        renamed = self.client.patch(self._url(), {"name": "Renamed after release"})
        assert renamed.status_code == status.HTTP_200_OK, renamed.json()

    def test_an_unchanged_managed_by_does_not_make_an_ordinary_save_a_release(self) -> None:
        gui_workflow = self._create_workflow(managed_by=None)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}",
            {"managed_by": None, "name": "Renamed in the UI", "description": "Edited"},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        gui_workflow.refresh_from_db()
        assert gui_workflow.name == "Renamed in the UI"

    def test_each_revision_keeps_the_ref_of_the_push_that_produced_it(self) -> None:
        client, auth = self._api_key_client()
        created = client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {
                "name": "Pushed",
                "managed_by": "code",
                "source_repository": "github.com/example/flows",
                "source_path": "workflows/pushed.ts",
                "source_ref": "1111111",
                "actions": [TRIGGER_ACTION, EXIT_ACTION],
            },
            format="json",
            headers=auth,
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        url = f"/api/projects/{self.team.id}/hog_flows/{created.json()['id']}"
        updated = client.patch(
            url,
            {"source_ref": "2222222", "actions": [TRIGGER_ACTION, {**EXIT_ACTION, "name": "done"}]},
            format="json",
            headers=auth,
        )
        assert updated.status_code == status.HTTP_200_OK, updated.json()

        refs = {v: self.client.get(f"{url}/revisions/{v}").json()["content"].get("source_ref") for v in (1, 2)}
        assert refs == {1: "1111111", 2: "2222222"}

        assert self.client.patch(url, {"managed_by": "gui"}).status_code == status.HTTP_200_OK
        restored = self.client.post(f"{url}/revisions/1/restore", {})
        assert restored.status_code == status.HTTP_200_OK, restored.json()
        draft = HogFlow.objects.get(id=created.json()["id"]).draft
        assert draft is not None
        assert "source_ref" not in draft

    def test_a_push_reclaims_a_released_workflow_in_one_write(self) -> None:
        gui_workflow = self._create_workflow(managed_by=HogFlow.ManagedBy.GUI)
        client, auth = self._api_key_client()

        response = client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}",
            {"managed_by": "code", "name": "Claimed by a push"},
            headers=auth,
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        gui_workflow.refresh_from_db()
        assert gui_workflow.managed_by == HogFlow.ManagedBy.CODE
        assert gui_workflow.name == "Claimed by a push"
