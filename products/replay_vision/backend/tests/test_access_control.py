from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.replay_vision.backend.models.vision_action import VisionAction
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

    def test_user_access_level_exposed_on_vision_action(self) -> None:
        self._set_replay_scanner_resource_default("viewer")
        self.client.force_login(self.other_user)

        VisionAction.objects.for_team(self.team.id).create(
            team=self.team, created_by=self.user, name="digest", scanner=self.scanner
        )
        resp = self.client.get(self.actions_url)
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["results"][0]["user_access_level"], "viewer")
