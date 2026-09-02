from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.cdp.templates.fixtures import template_slack
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.constants import AvailableFeature
from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionTemplate
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_alert import (
    VisionAlertConfiguration,
    VisionAlertEvent,
    VisionAlertState,
)


class _VisionAlertAPITestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = self._create_scanner()
        self.base_url = f"/api/projects/{self.team.id}/vision/alerts/"

    def _create_scanner(
        self, name: str = "Checkout monitor", team: Team | None = None, scanner_type: str = ScannerType.MONITOR
    ) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=team or self.team,
            name=name,
            scanner_type=scanner_type,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )

    def _metric_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scanner_id": str(self.scanner.id),
            "name": "Too many failures",
            "kind": "metric",
            "threshold": 5,
            "selection": {"verdict": ["fail"]},
        }
        payload.update(overrides)
        return payload

    def _match_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scanner_id": str(self.scanner.id),
            "name": "Every failed checkout",
            "kind": "match",
            "selection": {"verdict": ["fail"]},
        }
        payload.update(overrides)
        return payload

    def _create_via_api(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.post(self.base_url, payload or self._metric_payload(), format="json")
        assert response.status_code == 201, response.json()
        return response.json()


class TestVisionAlertCRUD(_VisionAlertAPITestCase):
    def test_create_metric_alert_defaults(self) -> None:
        data = self._create_via_api()
        assert data["kind"] == "metric"
        assert data["state"] == "not_firing"
        assert data["metric"] == "count"
        assert data["direction"] == "above"
        assert data["window_days"] == 1
        assert data["first_enabled_at"] is not None
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).get(id=data["id"])
        assert alert.created_by == self.user
        assert alert.scanner_id == self.scanner.id

    def test_create_match_alert_has_no_schedule(self) -> None:
        data = self._create_via_api(self._match_payload())
        assert data["kind"] == "match"
        assert data["state"] == "not_firing"
        assert data["next_check_at"] is None

    @parameterized.expand(
        [
            ("metric_without_threshold", {"kind": "metric", "threshold": None}, "threshold"),
            ("match_with_threshold", {"kind": "match", "threshold": 5}, "threshold"),
            ("bad_window", {"kind": "metric", "threshold": 5, "window_days": 2}, "window_days"),
            (
                "avg_score_on_monitor_scanner",
                {"kind": "metric", "threshold": 5, "metric": "avg_score"},
                "metric",
            ),
            (
                "datapoints_exceed_periods",
                {"kind": "metric", "threshold": 5, "evaluation_periods": 2, "datapoints_to_alarm": 3},
                "datapoints_to_alarm",
            ),
            (
                "match_with_metric_config",
                {"kind": "match", "threshold": None, "window_days": 7},
                "window_days",
            ),
        ]
    )
    def test_create_validation_rejected(self, _name: str, overrides: dict[str, Any], error_field: str) -> None:
        payload = self._metric_payload()
        payload.pop("threshold")
        payload.pop("selection")
        payload.update(overrides)
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == 400, response.json()
        assert response.json()["attr"].startswith(error_field), response.json()

    def test_duplicate_name_is_a_field_error(self) -> None:
        self._create_via_api()
        response = self.client.post(self.base_url, self._metric_payload(), format="json")
        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "name"

    def test_create_without_name_gets_default(self) -> None:
        payload = self._metric_payload()
        payload.pop("name")
        response = self.client.post(self.base_url, payload, format="json")
        assert response.status_code == 201, response.json()
        assert response.json()["name"] == "Untitled alert"

    def test_kind_and_scanner_are_immutable(self) -> None:
        data = self._create_via_api()
        response = self.client.patch(f"{self.base_url}{data['id']}/", {"kind": "match"}, format="json")
        assert response.status_code == 400
        other_scanner = self._create_scanner(name="Other scanner")
        response = self.client.patch(
            f"{self.base_url}{data['id']}/", {"scanner_id": str(other_scanner.id)}, format="json"
        )
        assert response.status_code == 400

    def test_alerts_are_team_scoped(self) -> None:
        data = self._create_via_api()
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        self.organization_membership.delete()
        other_url = f"/api/projects/{other_team.id}/vision/alerts/"
        response = self.client.get(other_url)
        assert response.status_code in (403, 404)
        # Same-team retrieval from a different project id must not leak the alert.
        assert not VisionAlertConfiguration.objects.for_team(other_team.id).filter(id=data["id"]).exists()

    def test_list_filters_by_scanner(self) -> None:
        self._create_via_api()
        other_scanner = self._create_scanner(name="Other scanner")
        self._create_via_api(self._metric_payload(name="Other alert", scanner_id=str(other_scanner.id)))
        response = self.client.get(self.base_url, {"scanner_id": str(other_scanner.id)})
        assert response.status_code == 200
        results = response.json()["results"]
        assert [r["name"] for r in results] == ["Other alert"]

    def test_match_kind_lifecycle_write_is_rejected_by_db(self) -> None:
        data = self._create_via_api(self._match_payload())
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                VisionAlertConfiguration.all_teams.filter(id=data["id"]).update(state=VisionAlertState.FIRING)


class TestVisionAlertControlPlane(_VisionAlertAPITestCase):
    def _patch(self, alert_id: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.patch(f"{self.base_url}{alert_id}/", body, format="json")
        assert response.status_code == 200, response.json()
        return response.json()

    def test_disable_enable_round_trip_writes_audit_rows(self) -> None:
        data = self._create_via_api()
        self._patch(data["id"], {"enabled": False})
        self._patch(data["id"], {"enabled": True})
        kinds = list(
            VisionAlertEvent.objects.filter(alert_id=data["id"]).order_by("created_at").values_list("kind", flat=True)
        )
        assert kinds == [VisionAlertEvent.Kind.DISABLE, VisionAlertEvent.Kind.ENABLE]

    def test_snooze_and_unsnooze(self) -> None:
        data = self._create_via_api()
        until = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
        snoozed = self._patch(data["id"], {"snooze_until": until})
        assert snoozed["state"] == "snoozed"
        unsnoozed = self._patch(data["id"], {"snooze_until": None})
        assert unsnoozed["state"] == "not_firing"
        assert unsnoozed["snooze_until"] is None

    def test_snoozing_a_match_alert_keeps_it_stateless(self) -> None:
        data = self._create_via_api(self._match_payload())
        until = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
        snoozed = self._patch(data["id"], {"snooze_until": until})
        assert snoozed["state"] == "not_firing"
        assert snoozed["snooze_until"] is not None
        unsnoozed = self._patch(data["id"], {"snooze_until": None})
        assert unsnoozed["snooze_until"] is None

    def test_threshold_change_resets_state_and_recheck(self) -> None:
        data = self._create_via_api()
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).get(id=data["id"])
        alert.next_check_at = datetime.now(UTC) + timedelta(hours=1)
        alert.save(update_fields=["next_check_at"])
        updated = self._patch(data["id"], {"threshold": 10})
        assert updated["threshold"] == 10
        assert updated["next_check_at"] is None
        kinds = VisionAlertEvent.objects.filter(alert_id=data["id"]).values_list("kind", flat=True)
        assert VisionAlertEvent.Kind.THRESHOLD_CHANGE in kinds

    def test_reset_requires_broken_state(self) -> None:
        data = self._create_via_api()
        response = self.client.post(f"{self.base_url}{data['id']}/reset/")
        assert response.status_code == 400
        VisionAlertConfiguration.all_teams.filter(id=data["id"]).update(
            state=VisionAlertState.BROKEN, consecutive_failures=5
        )
        response = self.client.post(f"{self.base_url}{data['id']}/reset/")
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["state"] == "not_firing"
        assert body["consecutive_failures"] == 0

    def test_alert_cap_enforced(self) -> None:
        with patch("products.replay_vision.backend.api.vision_alerts.MAX_ALERTS_PER_TEAM", 1):
            self._create_via_api()
            response = self.client.post(self.base_url, self._metric_payload(name="Second"), format="json")
            assert response.status_code == 400


class TestVisionAlertDestinations(_VisionAlertAPITestCase):
    def _sync_destination_templates(self) -> None:
        sync_template_to_db(template_slack)
        HogFunctionTemplate.objects.get_or_create(
            template_id="template-webhook",
            defaults={
                "sha": "1.0.0",
                "name": "Webhook",
                "description": "Generic webhook template",
                "code": "return event",
                "code_language": "hog",
                "inputs_schema": [{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
                "type": "destination",
                "status": "stable",
                "category": ["Integrations"],
                "free": True,
            },
        )

    @parameterized.expand(
        [
            (
                "metric",
                4,
                {
                    "$replay_vision_alert_firing",
                    "$replay_vision_alert_resolved",
                    "$replay_vision_alert_auto_disabled",
                    "$replay_vision_alert_errored",
                },
            ),
            ("match", 1, {"$replay_vision_alert_match"}),
        ]
    )
    def test_webhook_destination_provisions_per_kind(
        self, kind: str, expected_count: int, expected_event_ids: set[str]
    ) -> None:
        self._sync_destination_templates()
        payload = self._metric_payload() if kind == "metric" else self._match_payload()
        created = self._create_via_api(payload)
        response = self.client.post(
            f"{self.base_url}{created['id']}/destinations/",
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        assert response.status_code == 201, response.json()
        ids = response.json()["hog_function_ids"]
        assert len(ids) == expected_count
        hog_functions = HogFunction.objects.filter(id__in=ids)
        assert {(hf.filters or {})["events"][0]["id"] for hf in hog_functions} == expected_event_ids

    def test_destroy_soft_deletes_destinations(self) -> None:
        self._sync_destination_templates()
        created = self._create_via_api(self._match_payload())
        response = self.client.post(
            f"{self.base_url}{created['id']}/destinations/",
            {"type": "webhook", "webhook_url": "https://example.com/hook"},
            format="json",
        )
        ids = response.json()["hog_function_ids"]
        response = self.client.delete(f"{self.base_url}{created['id']}/")
        assert response.status_code == 204
        assert not VisionAlertConfiguration.objects.for_team(self.team.id).filter(id=created["id"]).exists()
        assert set(HogFunction.objects.filter(id__in=ids).values_list("deleted", flat=True)) == {True}


class TestVisionAlertAccessControl(_VisionAlertAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")

    def _set_scanner_default(self, access_level: str) -> None:
        AccessControl.objects.update_or_create(
            team=self.team,
            resource="replay_scanner",
            resource_id=None,
            organization_member=None,
            role=None,
            defaults={"access_level": access_level},
        )

    def test_scanner_viewer_cannot_create_or_update_alert(self) -> None:
        created = self._create_via_api()
        self._set_scanner_default("viewer")
        self.client.force_login(self.other_user)
        create_resp = self.client.post(self.base_url, self._metric_payload(name="Blocked"), format="json")
        assert create_resp.status_code == 403, create_resp.json()
        patch_resp = self.client.patch(f"{self.base_url}{created['id']}/", {"threshold": 9}, format="json")
        assert patch_resp.status_code == 403, patch_resp.json()

    def test_scanner_resource_none_blocks_list_and_retrieve(self) -> None:
        created = self._create_via_api()
        self._set_scanner_default("none")
        self.client.force_login(self.other_user)
        list_resp = self.client.get(self.base_url)
        assert list_resp.status_code == 403, list_resp.json()
        retrieve_resp = self.client.get(f"{self.base_url}{created['id']}/")
        assert retrieve_resp.status_code == 403, retrieve_resp.json()

    def test_object_level_scanner_restriction_hides_alerts_from_list(self) -> None:
        visible = self._create_via_api()
        other_scanner = self._create_scanner(name="Restricted")
        hidden = self._create_via_api(self._metric_payload(name="Hidden", scanner_id=str(other_scanner.id)))
        AccessControl.objects.create(
            team=self.team,
            resource="replay_scanner",
            resource_id=str(other_scanner.id),
            access_level="none",
        )
        self.client.force_login(self.other_user)
        list_resp = self.client.get(self.base_url)
        assert list_resp.status_code == 200, list_resp.json()
        assert [a["id"] for a in list_resp.json()["results"]] == [visible["id"]]
        retrieve_resp = self.client.get(f"{self.base_url}{hidden['id']}/")
        assert retrieve_resp.status_code == 403, retrieve_resp.json()

    def test_session_recording_resource_none_blocks_config_actions(self) -> None:
        AccessControl.objects.create(
            team=self.team, resource="session_recording", resource_id=None, access_level="none"
        )
        self.client.force_login(self.other_user)
        response = self.client.post(self.base_url, self._metric_payload(), format="json")
        assert response.status_code == 403, response.json()
        assert "session_recording" in response.json()["detail"]

    def test_config_actions_require_session_recording_read_scope(self) -> None:
        write_only = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="write-only",
            user=self.user,
            secure_value=hash_key_value(write_only),
            scopes=["vision_alert:write"],
        )
        response = self.client.post(
            self.base_url,
            self._metric_payload(),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {write_only}",
        )
        assert response.status_code == 403, response.json()

        full = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="full",
            user=self.user,
            secure_value=hash_key_value(full),
            scopes=["vision_alert:write", "session_recording:read"],
        )
        response = self.client.post(
            self.base_url,
            self._metric_payload(name="Scoped create"),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {full}",
        )
        assert response.status_code == 201, response.json()
