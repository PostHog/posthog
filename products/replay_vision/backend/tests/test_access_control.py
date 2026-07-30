from unittest.mock import MagicMock, patch

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.vision_action import VisionAction, VisionActionRun, VisionActionRunStatus
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase
from products.replay_vision.backend.tests.test_vision_actions_api import _VisionActionAPITestCase

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


class _AccessControlTestCase(_VisionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")

    def _set_resource_default(self, resource: str, access_level: str) -> None:
        AccessControl.objects.update_or_create(
            team=self.team,
            resource=resource,
            resource_id=None,
            organization_member=None,
            role=None,
            defaults={"access_level": access_level},
        )

    def _grant_object_access(self, user: User, resource: str, resource_id: str, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _personal_api_key(self, user: User, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="ac-test", user=user, secure_value=hash_key_value(value), scopes=scopes)
        return value


class TestReplayScannerAccessControl(_AccessControlTestCase):
    def test_resource_default_none_blocks_list_and_retrieve(self) -> None:
        scanner = self._create_scanner()
        self._set_resource_default("replay_scanner", "none")

        self.client.force_login(self.other_user)
        list_resp = self.client.get(self.scanners_url)
        self.assertEqual(list_resp.status_code, 403, list_resp.json())

        retrieve_resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(retrieve_resp.status_code, 403, retrieve_resp.json())

    def test_viewer_access_cannot_create_or_update_scanner(self) -> None:
        scanner = self._create_scanner()
        self._set_resource_default("replay_scanner", "viewer")

        self.client.force_login(self.other_user)
        create_resp = self.client.post(
            self.scanners_url,
            data={
                "name": "viewer-created",
                "scanner_type": "monitor",
                "scanner_config": {"prompt": "well?"},
                "model": "gemini-3-flash",
            },
            format="json",
        )
        self.assertEqual(create_resp.status_code, 403, create_resp.json())

        update_resp = self.client.patch(f"{self.scanners_url}{scanner.id}/", data={"name": "renamed"}, format="json")
        self.assertEqual(update_resp.status_code, 403, update_resp.json())

    def test_object_level_grant_overrides_resource_default_none(self) -> None:
        allowed_scanner = self._create_scanner(name="allowed")
        blocked_scanner = self._create_scanner(name="blocked")
        self._set_resource_default("replay_scanner", "none")
        self._grant_object_access(self.other_user, "replay_scanner", str(allowed_scanner.id), "viewer")

        self.client.force_login(self.other_user)
        allowed_resp = self.client.get(f"{self.scanners_url}{allowed_scanner.id}/")
        self.assertEqual(allowed_resp.status_code, 200, allowed_resp.json())

        blocked_resp = self.client.get(f"{self.scanners_url}{blocked_scanner.id}/")
        self.assertEqual(blocked_resp.status_code, 403, blocked_resp.json())

    def test_user_access_level_exposed_on_scanner(self) -> None:
        scanner = self._create_scanner()
        self._set_resource_default("replay_scanner", "viewer")

        self.client.force_login(self.other_user)
        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["user_access_level"], "viewer")

    def test_access_controls_endpoint_requires_access_control_scope(self) -> None:
        # Regression guard: ReplayScannerViewSet overrides dangerously_get_required_scopes for its
        # own config actions — it must still fall through to AccessControlViewSetMixin's scope
        # requirements for access_controls/resource_access_controls, or personal-API-key callers
        # would bypass the access_control:read/write scope check entirely.
        scanner = self._create_scanner()
        read_key = self._personal_api_key(self.user, ["replay_scanner:read", "session_recording:read"])
        ac_key = self._personal_api_key(
            self.user, ["replay_scanner:read", "session_recording:read", "access_control:read"]
        )

        denied = self.client.get(
            f"{self.scanners_url}{scanner.id}/access_controls/", HTTP_AUTHORIZATION=f"Bearer {read_key}"
        )
        self.assertEqual(denied.status_code, 403, denied.json())

        allowed = self.client.get(
            f"{self.scanners_url}{scanner.id}/access_controls/", HTTP_AUTHORIZATION=f"Bearer {ac_key}"
        )
        self.assertEqual(allowed.status_code, 200, allowed.json())

    @patch("products.replay_vision.backend.api.trigger.sync_connect")
    @patch("products.replay_vision.backend.api.trigger.async_to_sync")
    def test_bulk_observe_requires_replay_scanner_editor_level(
        self, mock_async_to_sync: MagicMock, mock_sync_connect: MagicMock
    ) -> None:
        # bulk_observe is a newer write action alongside observe/create/update/destroy — this guards
        # against it silently losing RBAC coverage (e.g. an incomplete scope_object_write_actions entry)
        # the way observe's object-level check protects that action.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        scanner = self._create_scanner()
        self._set_resource_default("replay_scanner", "viewer")
        bulk_url = f"{self.scanners_url}{scanner.id}/bulk_observe/"

        self.client.force_login(self.other_user)
        denied = self.client.post(bulk_url, data={"session_ids": ["s1"]}, format="json")
        self.assertEqual(denied.status_code, 403, denied.json())

        self._grant_object_access(self.other_user, "replay_scanner", str(scanner.id), "editor")
        allowed = self.client.post(bulk_url, data={"session_ids": ["s1"]}, format="json")
        self.assertEqual(allowed.status_code, 202, allowed.json())

    def test_estimate_treats_denied_scanner_as_not_found(self) -> None:
        # A scanner_id the caller can't view must be rejected the same way as one that doesn't exist —
        # otherwise comparing responses (with/without the id) leaks whether it exists and its credit usage.
        # A resource-wide "none" default would block the whole `estimate` action at the permission layer
        # before this object-level check ever runs, so deny only this one scanner instead.
        blocked_scanner = self._create_scanner(name="blocked")
        self._grant_object_access(self.other_user, "replay_scanner", str(blocked_scanner.id), "none")

        self.client.force_login(self.other_user)
        resp = self.client.post(
            f"{self.scanners_url}estimate/", data={"scanner_id": str(blocked_scanner.id)}, format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "scanner_id")


class TestVisionActionAccessControlInheritance(_VisionActionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")

    def _set_replay_scanner_resource_default(self, access_level: str) -> None:
        AccessControl.objects.update_or_create(
            team=self.team,
            resource="replay_scanner",
            resource_id=None,
            organization_member=None,
            role=None,
            defaults={"access_level": access_level},
        )

    def _grant_scanner_access(self, user: User, scanner_id: str, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="replay_scanner",
            resource_id=scanner_id,
            access_level=access_level,
            organization_member=membership,
        )

    def test_vision_action_inherits_replay_scanner_resource_level(self) -> None:
        # vision_action has no resource-level rule of its own (RESOURCE_INHERITANCE_MAP points it at
        # replay_scanner) — a "none" default on replay_scanner must block vision_action reads too.
        self._set_replay_scanner_resource_default("none")

        self.client.force_login(self.other_user)
        resp = self.client.get(self.actions_url)
        self.assertEqual(resp.status_code, 403, resp.json())

    def test_vision_action_create_requires_replay_scanner_editor_level(self) -> None:
        self._set_replay_scanner_resource_default("viewer")

        self.client.force_login(self.other_user)
        resp = self.client.post(self.actions_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 403, resp.json())

        self._set_replay_scanner_resource_default("editor")
        resp = self.client.post(self.actions_url, data=self._create_payload(name="second-action"), format="json")
        self.assertEqual(resp.status_code, 201, resp.json())

    def test_vision_action_has_no_own_access_controls_endpoint(self) -> None:
        # Deliberate: vision_action is configured via the single replay_scanner rule, not its own
        # object-level grants (see the comment on VisionActionViewSet).
        action = VisionAction.objects.for_team(self.team.id).create(
            team=self.team,
            created_by=self.user,
            name="digest",
            scanner=self.scanner,
        )
        resp = self.client.get(f"{self.actions_url}{action.id}/access_controls/")
        self.assertEqual(resp.status_code, 404, resp.json())

    def test_retrieve_blocked_when_selection_scanner_is_denied(self) -> None:
        # `selection.scanner_ids` lets an action pull observations from scanners beyond the one it's
        # bound to — retrieving the action must authorize those too, not just the bound scanner. The
        # bound scanner rides the ambient default ("editor", unrestricted); only `other_scanner` gets an
        # explicit object-level denial, isolating the new selection-scanner check from the bound one.
        other_scanner = self._create_scanner(name="other-scanner")
        self._grant_scanner_access(self.other_user, str(other_scanner.id), "none")
        action = VisionAction.objects.for_team(self.team.id).create(
            team=self.team,
            created_by=self.user,
            name="digest",
            scanner=self.scanner,
            selection={"scanner_ids": [str(self.scanner.id), str(other_scanner.id)]},
        )

        self.client.force_login(self.other_user)
        resp = self.client.get(f"{self.actions_url}{action.id}/")
        self.assertEqual(resp.status_code, 403, resp.json())

    def test_update_revalidates_selection_scanner_when_only_delivery_changes(self) -> None:
        # A PATCH that touches neither `scanner` nor `selection` must still revalidate the action's
        # existing selection — otherwise an editor of the bound scanner could freely rewrite delivery
        # destinations on an action whose (untouched) selection reads from a scanner they can't access.
        other_scanner = self._create_scanner(name="other-scanner")
        self._grant_scanner_access(self.other_user, str(other_scanner.id), "none")
        action = VisionAction.objects.for_team(self.team.id).create(
            team=self.team,
            created_by=self.user,
            name="digest",
            scanner=self.scanner,
            selection={"scanner_ids": [str(self.scanner.id), str(other_scanner.id)]},
        )

        self.client.force_login(self.other_user)
        resp = self.client.patch(
            f"{self.actions_url}{action.id}/",
            data={"delivery_config": [{"type": "slack", "integration_id": self.integration.id, "channel": "#new"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.json())
        action.refresh_from_db()
        self.assertEqual(action.delivery_config, [])

    def test_run_report_blocked_when_observation_scanner_is_denied(self) -> None:
        # A run's observation_ids reflect whatever scanners it actually drew from at run time. If
        # `selection` is edited later (or access is revoked), a historical run can still cite an
        # observation from a scanner the caller can no longer see — the report must not expose it, even
        # though the action's current selection and bound scanner remain fully accessible.
        other_scanner = self._create_scanner(name="other-scanner")
        self._grant_scanner_access(self.other_user, str(other_scanner.id), "none")
        action = VisionAction.objects.for_team(self.team.id).create(
            team=self.team, created_by=self.user, name="digest", scanner=self.scanner
        )
        observation = ReplayObservation.objects.create(scanner=other_scanner, session_id="sess-1")
        run = VisionActionRun.all_teams.create(
            team=self.team,
            vision_action=action,
            idempotency_key="run-1",
            status=VisionActionRunStatus.COMPLETED,
            observation_ids=[str(observation.id)],
        )

        self.client.force_login(self.other_user)
        runs_url = f"{self.actions_url}{action.id}/runs/"
        list_resp = self.client.get(runs_url)
        self.assertEqual(list_resp.status_code, 200, list_resp.json())  # lightweight rows carry no report body

        retrieve_resp = self.client.get(f"{runs_url}{run.id}/")
        self.assertEqual(retrieve_resp.status_code, 403, retrieve_resp.json())

    def test_update_cannot_rebind_action_onto_a_restricted_scanner(self) -> None:
        # Editor on `self.scanner`, but only viewer on `other_scanner` — enough to read it (so the
        # serializer's separate readable-scanner-ids check doesn't fire first) but not enough to bind
        # an action to it.
        other_scanner = self._create_scanner(name="other-scanner")
        self._set_replay_scanner_resource_default("none")
        self._grant_scanner_access(self.other_user, str(self.scanner.id), "editor")
        self._grant_scanner_access(self.other_user, str(other_scanner.id), "viewer")
        action = VisionAction.objects.for_team(self.team.id).create(
            team=self.team, created_by=self.user, name="digest", scanner=self.scanner
        )

        self.client.force_login(self.other_user)
        resp = self.client.patch(
            f"{self.actions_url}{action.id}/", data={"scanner": str(other_scanner.id)}, format="json"
        )
        self.assertEqual(resp.status_code, 403, resp.json())
        action.refresh_from_db()
        self.assertEqual(action.scanner_id, self.scanner.id)
