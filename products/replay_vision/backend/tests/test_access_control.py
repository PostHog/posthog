from unittest.mock import MagicMock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.vision_action import VisionAction, VisionActionRun, VisionActionRunStatus
from products.replay_vision.backend.tests.helpers import create_experiment, snapshot_for
from products.replay_vision.backend.tests.test_api import _VisionAPITestCase
from products.replay_vision.backend.tests.test_vision_actions_api import _VisionActionAPITestCase


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

    @patch("products.replay_vision.backend.api.trigger.sync_connect")
    @patch("products.replay_vision.backend.api.trigger.async_to_sync")
    def test_inline_scan_requires_resource_level_editor(
        self, mock_async_to_sync: MagicMock, mock_sync_connect: MagicMock
    ) -> None:
        # inline_scan takes no scanner id, so an object-level grant can't narrow it the way it does for
        # bulk_observe above. Without a resource-level check, editor on any one scanner would let a
        # user run arbitrary configs and spend the org's credits.
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()
        scanner = self._create_scanner()
        self._set_resource_default("replay_scanner", "viewer")
        inline_url = f"{self.scanners_url}inline_scan/"
        body = {"session_ids": ["s1"], "prompt": "did the user rage click?"}

        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(inline_url, data=body, format="json").status_code, 403)

        # Editor on one specific scanner is what gets bulk_observe through; it must not be enough here.
        self._grant_object_access(self.other_user, "replay_scanner", str(scanner.id), "editor")
        self.assertEqual(self.client.post(inline_url, data=body, format="json").status_code, 403)

        self._set_resource_default("replay_scanner", "editor")
        self.assertEqual(self.client.post(inline_url, data=body, format="json").status_code, 202)

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

    def test_backfills_inherit_scanner_object_rbac(self) -> None:
        scanner = self._create_scanner()
        self._set_resource_default("replay_scanner", "none")
        self.client.force_login(self.other_user)
        url = f"{self.scanners_url}{scanner.id}/backfills/"
        self.assertEqual(self.client.get(url).status_code, 403)
        window = {"window_start": "2026-01-01T00:00:00Z", "window_end": "2026-02-01T00:00:00Z"}
        self.assertEqual(self.client.post(f"{url}estimate/", window, format="json").status_code, 403)
        self.assertEqual(self.client.post(url, window, format="json").status_code, 403)

    def test_experiment_targeting_rejects_an_experiment_the_caller_cannot_view(self) -> None:
        # A scanner-editor without experiment access must not be able to confirm an experiment's
        # existence via the targeting validation response; a denied experiment reads as not-found.
        experiment = create_experiment(self.team, "denied-flag")
        self._set_resource_default("experiment", "none")
        self._grant_object_access(self.other_user, "experiment", str(experiment.id), "none")

        self.client.force_login(self.other_user)
        resp = self.client.post(
            self.scanners_url,
            data={
                "name": "targeting-denied",
                "scanner_type": "monitor",
                "scanner_config": {"prompt": "p"},
                "model": "gemini-3.7-flash",
                "experiment_targeting": {
                    "experiment_id": experiment.id,
                },
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "experiment_targeting")

    def test_experiment_targeting_hidden_from_a_viewer_without_experiment_access(self) -> None:
        # A scanner is viewable at a coarser grain than its targeted experiment; a viewer who can't
        # access the experiment must not learn its id or variants from the scanner payload.
        experiment = create_experiment(self.team, "hidden-flag")
        targeting = {"experiment_id": experiment.id, "variant": "test"}
        scanner = self._create_scanner(name="targeted", experiment_targeting=targeting)
        self._set_resource_default("replay_scanner", "viewer")
        self._set_resource_default("experiment", "none")
        self._grant_object_access(self.other_user, "experiment", str(experiment.id), "none")

        self.client.force_login(self.other_user)
        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertIsNone(resp.json()["experiment_targeting"])

        # The creator, who can view the experiment, still sees it.
        self.client.force_login(self.user)
        resp = self.client.get(f"{self.scanners_url}{scanner.id}/")
        self.assertEqual(resp.json()["experiment_targeting"], targeting)

    def test_save_by_a_viewer_denied_the_experiment_keeps_the_targeting(self) -> None:
        # The API redacts experiment_targeting to null for such an editor, and the editor form
        # writes the whole object back on save. Without the write-side guard, renaming the scanner
        # would silently clear targeting the caller can't even see.
        experiment = create_experiment(self.team, "hidden-flag")
        targeting = {"experiment_id": experiment.id, "variant": "test"}
        scanner = self._create_scanner(name="targeted", experiment_targeting=targeting)
        self._set_resource_default("replay_scanner", "editor")
        self._set_resource_default("experiment", "none")
        self._grant_object_access(self.other_user, "experiment", str(experiment.id), "none")

        self.client.force_login(self.other_user)
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/",
            data={"name": "renamed", "experiment_targeting": None},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        scanner.refresh_from_db()
        self.assertEqual(scanner.experiment_targeting, targeting)

        # The creator, who can view the experiment, can still clear it explicitly.
        self.client.force_login(self.user)
        resp = self.client.patch(
            f"{self.scanners_url}{scanner.id}/", data={"experiment_targeting": None}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.json())
        scanner.refresh_from_db()
        self.assertIsNone(scanner.experiment_targeting)

    def test_estimate_treats_a_denied_experiment_targeting_as_not_found(self) -> None:
        # The query runner's own access check answers a denied experiment with a 403, which would
        # confirm the hidden id exists; the endpoint must answer 400 not-found, like the scanner
        # write path does.
        experiment = create_experiment(self.team, "hidden-flag")
        self._set_resource_default("experiment", "none")
        self._grant_object_access(self.other_user, "experiment", str(experiment.id), "none")

        self.client.force_login(self.other_user)
        resp = self.client.post(
            f"{self.scanners_url}estimate/",
            data={"experiment_targeting": {"experiment_id": experiment.id}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.json())
        self.assertEqual(resp.json()["attr"], "experiment_targeting")

    def test_experiment_id_filter_returns_no_matches_for_an_inaccessible_experiment(self) -> None:
        # Guards the ?experiment_id= disclosure: a scanner-viewer who can't access the experiment must
        # not confirm a scanner targets it via the filter's match count. Distinct code path from the
        # serializer redaction above — the scanner is hidden from the list entirely, not just nulled.
        experiment = create_experiment(self.team, "hidden-flag")
        targeting = {"experiment_id": experiment.id, "variant": "test"}
        self._create_scanner(name="targeted", experiment_targeting=targeting)
        self._set_resource_default("replay_scanner", "viewer")
        self._set_resource_default("experiment", "none")
        self._grant_object_access(self.other_user, "experiment", str(experiment.id), "none")

        self.client.force_login(self.other_user)
        resp = self.client.get(f"{self.scanners_url}?experiment_id={experiment.id}")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual(resp.json()["results"], [])

        # The creator, who can view the experiment, gets the match.
        self.client.force_login(self.user)
        resp = self.client.get(f"{self.scanners_url}?experiment_id={experiment.id}")
        self.assertEqual([s["name"] for s in resp.json()["results"]], ["targeted"])

    def test_experiment_id_filter_resolves_the_current_project_alias(self) -> None:
        # The filter must resolve @current the way the viewset does, not pass the literal string to
        # the DB lookup (which 500s). The user's current team is set by the test harness.
        experiment = create_experiment(self.team, "aliased-flag")
        targeting = {"experiment_id": experiment.id}
        self._create_scanner(name="targeted", experiment_targeting=targeting)

        resp = self.client.get(f"/api/environments/@current/vision/scanners/?experiment_id={experiment.id}")
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([s["name"] for s in resp.json()["results"]], ["targeted"])

    def test_observations_of_a_denied_experiment_scanner_read_as_not_found(self) -> None:
        # An experiment scanner's observations are the experiment's exposed sessions, so scanner +
        # session_recording access is not enough to read them: a caller denied the experiment must
        # not learn which sessions and people were exposed. Reads as not-found, not 403, matching
        # the targeting redaction. A non-targeted scanner the same caller can read is the control.
        experiment = create_experiment(self.team, "hidden-flag")
        self._set_resource_default("replay_scanner", "editor")
        self._set_resource_default("session_recording", "editor")
        self._set_resource_default("experiment", "none")
        self._grant_object_access(self.other_user, "experiment", str(experiment.id), "none")
        targeted = self._create_scanner(name="targeted", experiment_targeting={"experiment_id": experiment.id})
        plain = self._create_scanner(name="plain")
        # Observations carry the scanner's snapshot, so their experiment targeting is recorded on the row.
        ReplayObservation.objects.create(
            scanner=targeted, session_id="exposed-sess", scanner_snapshot=snapshot_for(targeted)
        )
        ReplayObservation.objects.create(scanner=plain, session_id="plain-sess", scanner_snapshot=snapshot_for(plain))

        self.client.force_login(self.other_user)
        targeted_url = self.observations_url(str(targeted.id))
        self.assertEqual(self.client.get(targeted_url).status_code, 404)
        self.assertEqual(self.client.get(f"{targeted_url}stats/").status_code, 404)

        # Same access, non-targeted scanner: the experiment gate must not have widened to a blanket block.
        plain_resp = self.client.get(self.observations_url(str(plain.id)))
        self.assertEqual(plain_resp.status_code, 200, plain_resp.json())
        self.assertEqual([o["session_id"] for o in plain_resp.json()["results"]], ["plain-sess"])

        # The session-wide dock endpoint drops the exposed session but keeps the readable one.
        dock_url = f"/api/environments/{self.team.id}/vision/observations/"
        dock_resp = self.client.get(f"{dock_url}?session_id=exposed-sess")
        self.assertEqual(dock_resp.status_code, 200, dock_resp.json())
        self.assertEqual(dock_resp.json()["results"], [])

    def test_retargeting_a_scanner_does_not_expose_historical_observations(self) -> None:
        # An observation's population is fixed at creation, so the read gate follows the experiment in
        # each row's snapshot, not the scanner's current targeting. Removing or changing targeting must
        # not turn historical rows from a restricted experiment readable.
        restricted = create_experiment(self.team, "restricted-flag")
        self._set_resource_default("replay_scanner", "editor")
        self._set_resource_default("session_recording", "editor")
        self._set_resource_default("experiment", "none")
        self._grant_object_access(self.other_user, "experiment", str(restricted.id), "none")

        scanner = self._create_scanner(name="retargeted", experiment_targeting={"experiment_id": restricted.id})
        # A row produced while the scanner targeted the restricted experiment.
        ReplayObservation.objects.create(
            scanner=scanner, session_id="restricted-sess", scanner_snapshot=snapshot_for(scanner)
        )
        # The editor clears targeting; the scanner's current targeting is now null.
        scanner.experiment_targeting = None
        scanner.save()
        ReplayObservation.objects.create(
            scanner=scanner, session_id="untargeted-sess", scanner_snapshot=snapshot_for(scanner)
        )

        self.client.force_login(self.other_user)
        # The scanner itself now reads (no current targeting), but the historical restricted row is withheld.
        resp = self.client.get(self.observations_url(str(scanner.id)))
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertEqual([o["session_id"] for o in resp.json()["results"]], ["untargeted-sess"])

        # Same through the session-wide dock: the restricted session stays hidden.
        dock_url = f"/api/environments/{self.team.id}/vision/observations/"
        dock_resp = self.client.get(f"{dock_url}?session_id=restricted-sess")
        self.assertEqual(dock_resp.status_code, 200, dock_resp.json())
        self.assertEqual(dock_resp.json()["results"], [])

    def test_dock_experiment_access_check_does_not_scale_per_scanner(self) -> None:
        # The dock's readable-scanner filter must batch the experiment-access lookup, not run one
        # query per targeted scanner — otherwise a team member can amplify one request into a query
        # per scanner. The query count stays flat as targeted scanners grow.
        experiment = create_experiment(self.team, "shared-flag")
        self._set_resource_default("replay_scanner", "editor")
        self._set_resource_default("session_recording", "editor")
        dock_url = f"/api/environments/{self.team.id}/vision/observations/?session_id=s1"
        self.client.force_login(self.other_user)

        self._create_scanner(name="t0", experiment_targeting={"experiment_id": experiment.id})
        self.client.get(dock_url)  # warm request-scoped caches so the two captures compare cleanly.
        with CaptureQueriesContext(connection) as one:
            self.assertEqual(self.client.get(dock_url).status_code, 200)
        for i in range(1, 6):
            self._create_scanner(name=f"t{i}", experiment_targeting={"experiment_id": experiment.id})
        with CaptureQueriesContext(connection) as six:
            self.assertEqual(self.client.get(dock_url).status_code, 200)
        self.assertEqual(len(one.captured_queries), len(six.captured_queries))


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
