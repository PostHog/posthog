from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.workflows.backend.api.hog_flow import HogFlowViewSet
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

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
        # A fresh client keeps the request session-free, so it classifies as API rather than WEB.
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
            # The guard runs inside get_object(), so it refuses before the revision is even looked up.
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

    def test_a_push_that_lands_mid_request_still_refuses_the_write(self) -> None:
        # The race the locked re-read exists for: the permission check passes on a workflow the app
        # owns, a push claims it, and the write lands on a row that is now code-managed. The flip runs
        # after get_object() returns, which is the moment between the check and the row lock.
        gui_workflow = self._create_workflow(managed_by=HogFlow.ManagedBy.GUI)
        original_get_object = HogFlowViewSet.get_object

        def get_object_then_push(viewset):
            hog_flow = original_get_object(viewset)
            HogFlow.objects.filter(pk=hog_flow.pk).update(managed_by=HogFlow.ManagedBy.CODE)
            return hog_flow

        with patch.object(HogFlowViewSet, "get_object", get_object_then_push):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}", {"name": "Renamed in the UI"}
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "immutable", response.json()
        gui_workflow.refresh_from_db()
        assert gui_workflow.name == "Welcome"

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
        # The whole request is refused, so the workflow that was fine to delete survives too.
        assert HogFlow.objects.filter(id=gui_workflow.id).exists()
        assert HogFlow.objects.filter(id=self.workflow.id).exists()

    @parameterized.expand(
        [
            ("mcp_transport", {"x-posthog-client": "mcp"}, True),
            # The MCP server forwards this header from the caller with no allow-list, so an agent can
            # declare itself the CLI even on an API key. The transport is what the guard has to read.
            ("cli_consumer_over_mcp", {"x-posthog-client": "mcp", "x-posthog-mcp-consumer": "posthog-cli"}, True),
            # A browser can set both of the headers `cli` is resolved from, so the guard must not take
            # the claim from a session-authenticated request.
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
            # Operating a workflow is not defining it: the file says what the workflow is, not what is
            # running right now. resume_email_sending is the sharpest of these, because PostHog itself
            # applies the pause and the endpoint is the only way out of it.
            # Both answer 400 on an empty body: the endpoint's own validation, which it only reaches
            # once the lock has let the request through.
            ("cancel_invocations", "/invocations/cancel"),
            ("resume_email_sending", "/resume_email_sending"),
        ]
    )
    def test_operating_a_code_managed_workflow_is_not_refused(self, _name: str, suffix: str) -> None:
        response = self.client.post(self._url(suffix), {})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("code") != "immutable", response.json()

    def test_a_schedule_write_is_refused_because_the_file_owns_the_trigger(self) -> None:
        response = self.client.post(self._url("/schedules"), {"rrule": "FREQ=DAILY"})

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "immutable"

    @parameterized.expand(
        [
            ("the_source", {"source_repository": "github.com/example/not-mine"}, "source_repository"),
            ("code_ownership", {"managed_by": "code"}, "managed_by"),
            # A form body spread into a PATCH must not move the lock, so the editor hears the refusal
            # rather than having the field silently stripped.
            ("code_ownership_in_a_form_body", {"managed_by": "code", "name": "Claimed"}, "managed_by"),
        ]
    )
    def test_a_web_request_cannot_claim(self, _name: str, payload: dict, field: str) -> None:
        gui_workflow = self._create_workflow(managed_by=None)
        gui_workflow.source_repository = None
        gui_workflow.save()

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}", payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
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
            # The editor fences every save with the copy it loaded, so the status-only save is never
            # literally status-only on the wire.
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
        # The editor loads a workflow and spreads the whole thing into its next save, so every save
        # carries the stored managed_by beside the fields the person actually changed.
        gui_workflow = self._create_workflow(managed_by=None)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{gui_workflow.id}",
            {"managed_by": None, "name": "Renamed in the UI", "description": "Edited"},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        gui_workflow.refresh_from_db()
        assert gui_workflow.name == "Renamed in the UI"

    def test_a_push_reclaims_a_released_workflow_in_one_write(self) -> None:
        # The refusal, the help text and the docs all promise that the next push claims the workflow
        # back, and a push sends the ownership and the content together.
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
