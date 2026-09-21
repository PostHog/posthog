from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db.utils import IntegrityError

from parameterized import parameterized

from posthog.models import Organization, Team

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger_1",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}


class TestHogFlowKey(APIBaseTest):
    def _payload(self, **overrides) -> dict:
        return {"name": "Test Flow", "status": "draft", "actions": [TRIGGER_ACTION], **overrides}

    def _create(self, **overrides):
        return self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._payload(**overrides))

    def test_create_echoes_the_key_back(self):
        response = self._create(key="onboarding-welcome")

        assert response.status_code == 201, response.json()
        assert response.json()["key"] == "onboarding-welcome"
        assert HogFlow.objects.get(id=response.json()["id"]).key == "onboarding-welcome"

    def test_create_without_a_key_leaves_it_null_and_never_collides(self):
        # The column is nullable and the many existing key-less rows must stay creatable:
        # NULLs are distinct under a Postgres unique index.
        first = self._create()
        second = self._create()

        assert first.status_code == 201, first.json()
        assert second.status_code == 201, second.json()
        assert first.json()["key"] is None
        assert second.json()["key"] is None

    @parameterized.expand([("foo?bar=baz",), ("foo/bar",), ("foo\\bar",), ("foo.bar",), ("foo bar",)])
    def test_create_with_an_invalid_charset_key_is_refused(self, key):
        response = self._create(key=key)

        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_key",
            "detail": "Only letters, numbers, hyphens (-) & underscores (_) are allowed.",
            "attr": "key",
        }
        assert not HogFlow.objects.filter(key=key).exists()

    def test_create_with_a_key_already_taken_in_the_team_is_refused(self):
        HogFlow.objects.create(team=self.team, name="Taken", created_by=self.user, key="onboarding-welcome")
        count = HogFlow.objects.count()

        response = self._create(key="onboarding-welcome")

        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "unique",
            "detail": "There is already a workflow with this key.",
            "attr": "key",
        }
        assert HogFlow.objects.count() == count

    def test_create_translates_a_concurrent_duplicate_key_into_the_same_field_error(self):
        # A concurrent create can slip past the unlocked pre-check, so the constraint violation
        # has to surface as the same 400 rather than a 500.
        with patch(
            "products.workflows.backend.api.hog_flow.HogFlow.objects.create",
            side_effect=IntegrityError('duplicate key value violates unique constraint "unique_key_for_team"'),
        ):
            response = self._create(key="onboarding-welcome")

        assert response.status_code == 400
        assert response.json() == {
            "type": "validation_error",
            "code": "unique",
            "detail": "There is already a workflow with this key.",
            "attr": "key",
        }

    def test_a_key_taken_in_another_team_does_not_block_a_create(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        HogFlow.objects.create(team=other_team, name="Theirs", key="onboarding-welcome")

        response = self._create(key="onboarding-welcome")

        assert response.status_code == 201, response.json()

    def test_patch_that_changes_the_key_is_refused(self):
        created = self._create(key="onboarding-welcome")
        flow_id = created.json()["id"]

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"key": "something-else"})

        assert response.status_code == 400
        assert response.json()["attr"] == "key"
        assert HogFlow.objects.get(id=flow_id).key == "onboarding-welcome"

    def test_patch_that_clears_the_key_is_refused(self):
        created = self._create(key="onboarding-welcome")
        flow_id = created.json()["id"]

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"key": None})

        assert response.status_code == 400
        assert response.json()["attr"] == "key"
        assert HogFlow.objects.get(id=flow_id).key == "onboarding-welcome"

    def test_patch_that_sets_a_key_on_a_key_less_workflow_is_refused(self):
        # Adoption is not in v1: a PATCH must not be a back door to claiming a key.
        created = self._create()
        flow_id = created.json()["id"]

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"key": "adopted"})

        assert response.status_code == 400
        assert response.json()["attr"] == "key"
        assert HogFlow.objects.get(id=flow_id).key is None

    def test_patch_that_repeats_the_stored_key_or_omits_it_is_allowed(self):
        created = self._create(key="onboarding-welcome")
        flow_id = created.json()["id"]

        repeated = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"key": "onboarding-welcome", "name": "Renamed"}
        )
        assert repeated.status_code == 200, repeated.json()

        omitted = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"name": "Renamed again"})
        assert omitted.status_code == 200, omitted.json()
        assert HogFlow.objects.get(id=flow_id).key == "onboarding-welcome"

    def test_list_filter_by_key_resolves_one_row_scoped_to_the_team(self):
        mine = HogFlow.objects.create(team=self.team, name="Mine", created_by=self.user, key="onboarding-welcome")
        HogFlow.objects.create(team=self.team, name="Other key", created_by=self.user, key="winback")
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other")
        HogFlow.objects.create(team=other_team, name="Theirs", key="onboarding-welcome")

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows?key=onboarding-welcome")

        assert response.status_code == 200, response.json()
        assert [flow["id"] for flow in response.json()["results"]] == [str(mine.id)]

    def test_list_filter_by_an_unknown_key_returns_nothing(self):
        HogFlow.objects.create(team=self.team, name="Mine", created_by=self.user, key="onboarding-welcome")

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows?key=not-here")

        assert response.status_code == 200, response.json()
        assert response.json()["results"] == []
