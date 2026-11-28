import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership, User
from posthog.test.api_keys import create_project_secret_api_key

from products.access_control.backend.facade.testing import create_access_control
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import ResourceType
from products.authorization.backend.presentation.querysets import filter_queryset
from products.experiments.backend.models.experiment import Experiment, ExperimentHoldout, ExperimentSavedMetric
from products.experiments.backend.test.test_facade_experiments import _CASES, ExperimentFixtures

from ee.api.test.base import APILicensedTest

_RECORDED_AT = datetime(2026, 3, 2, 9, 30, tzinfo=UTC)
_RUN_SPECIFIC_NUMBERS = frozenset({"id", "team_id", "experiment", "saved_metric", "exposure_cohort", "holdout_id"})
_RUN_SPECIFIC_TEXT = frozenset({"uuid", "distinct_id", "fingerprint", "flag_cleanup_task_id"})


def _stable_json(body: Any) -> str:
    """The body as indented JSON in its own key order, with a placeholder for each run-specific value.

    Equal values under the same parent key get the same placeholder, so the snapshot still shows which ids match.
    """
    placeholders: dict[str, dict[Any, str]] = defaultdict(dict)

    def visit(value: Any, parent: str) -> Any:
        if isinstance(value, dict):
            return {key: visit_entry(key, item, parent) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item, parent) for item in value]
        return value

    def visit_entry(key: str, value: Any, parent: str) -> Any:
        is_number = isinstance(value, int) and not isinstance(value, bool)
        if (key in _RUN_SPECIFIC_NUMBERS and is_number) or (key in _RUN_SPECIFIC_TEXT and isinstance(value, str)):
            kind = f"{parent}.{key}"
            return placeholders[kind].setdefault(value, f"<{kind} {len(placeholders[kind]) + 1}>")
        return visit(value, key)

    return json.dumps(visit(body, ""), indent=2)


@pytest.mark.usefixtures("unittest_snapshot")
class TestExperimentApiResponses(ExperimentFixtures, APILicensedTest):
    snapshot: Any

    @parameterized.expand(_CASES)
    def test_retrieve_returns_the_recorded_response(self, case: str) -> None:
        with time_machine.travel(_RECORDED_AT, tick=False):
            experiment = getattr(self, f"_create_{case}")()
            response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert _stable_json(response.json()) == self.snapshot

    def test_list_returns_the_recorded_response(self) -> None:
        with time_machine.travel(_RECORDED_AT, tick=False):
            for case in _CASES:
                getattr(self, f"_create_{case}")()
            response = self.client.get(f"/api/projects/{self.team.id}/experiments/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["count"] == len(_CASES)
        assert _stable_json(response.json()) == self.snapshot

    def test_write_responses_match_the_recorded_responses(self) -> None:
        url = f"/api/projects/{self.team.id}/experiments"
        with time_machine.travel(_RECORDED_AT, tick=False):
            holdout = ExperimentHoldout.objects.create(
                team=self.team,
                name="Holdout",
                created_by=self.user,
                filters=[{"properties": [], "rollout_percentage": 10}],
            )
            saved_metric = ExperimentSavedMetric.objects.create(
                team=self.team,
                name="Revenue",
                created_by=self.user,
                query={
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "revenue-metric",
                    "source": {"kind": "EventsNode", "event": "purchase"},
                },
            )
            created = self.client.post(
                f"{url}/",
                {
                    "name": "Checkout button",
                    "feature_flag_key": "checkout-button",
                    "holdout_id": holdout.id,
                    "parameters": {"variant_notes": {"test": "Green button"}},
                    "metrics": [
                        {
                            "kind": "ExperimentMetric",
                            "metric_type": "mean",
                            "uuid": "checkout-metric",
                            "source": {"kind": "EventsNode", "event": "checkout"},
                        }
                    ],
                    "saved_metrics_ids": [{"id": saved_metric.id, "metadata": {"type": "secondary"}}],
                    "allow_unknown_events": True,
                    "tags": ["checkout"],
                },
                format="json",
            )
            experiment_id = created.json()["id"]
            updated = self.client.patch(
                f"{url}/{experiment_id}/", {"description": "A green button converts better."}, format="json"
            )
            launched = self.client.post(f"{url}/{experiment_id}/launch/")
            duplicated = self.client.post(
                f"{url}/{experiment_id}/duplicate/",
                {"feature_flag_key": "checkout-button-copy", "name": "Checkout button copy"},
                format="json",
            )
            archived = self.client.post(f"{url}/{self._create_fully_populated().id}/archive/")

        responses = {
            "create": created,
            "update": updated,
            "launch": launched,
            "duplicate": duplicated,
            "archive": archived,
        }
        assert {name: response.status_code for name, response in responses.items()} == {
            "create": status.HTTP_201_CREATED,
            "update": status.HTTP_200_OK,
            "launch": status.HTTP_200_OK,
            "duplicate": status.HTTP_201_CREATED,
            "archive": status.HTTP_200_OK,
        }, {name: response.json() for name, response in responses.items()}
        assert _stable_json({name: response.json() for name, response in responses.items()}) == self.snapshot


class TestExperimentListAccess(ExperimentFixtures, APILicensedTest):
    def _experiment(
        self,
        name: str,
        created_by: User,
        access_level: str | None = None,
        member: OrganizationMembership | None = None,
    ) -> None:
        flag = self._flag(name.lower().replace(" ", "-"))
        experiment = Experiment.objects.create(team=self.team, name=name, created_by=created_by, feature_flag=flag)
        if access_level is not None:
            create_access_control(
                team_id=self.team.id,
                resource="experiment",
                resource_id=str(experiment.id),
                access_level=access_level,
                organization_member_id=member.id if member else None,
            )

    def _listed_names(self, query: str, credential: str) -> set[str]:
        headers: dict[str, str] = {}
        if credential == "personal_api_key":
            token = self.create_personal_api_key_with_scopes(["experiment:read"])
            headers = {"Authorization": f"Bearer {token}"}
            self.client.logout()
        elif credential == "project_secret_api_key":
            _, token = create_project_secret_api_key(self.team, scopes=["experiment:read"])
            headers = {"Authorization": f"Bearer {token}"}
            self.client.logout()

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?{query}", headers=headers)

        assert response.status_code == status.HTTP_200_OK, response.json()
        return {row["name"] for row in response.json()["results"]}

    def _names_the_sdk_shows(self, *, include_all_if_admin: bool) -> set[str]:
        experiments = filter_queryset(
            Experiment.objects.filter(team=self.team, archived=False),
            resource=Resource(type=ResourceType.EXPERIMENT, project_id=self.team.id),
            subject=Subject(user_id=self.user.id),
            include_all_if_admin=include_all_if_admin,
        )
        return set(experiments.values_list("name", flat=True))

    @parameterized.expand(
        [
            ("blocked_objects", OrganizationMembership.Level.MEMBER, None, "", "session"),
            ("grants_without_resource_access", OrganizationMembership.Level.MEMBER, "none", "", "session"),
            (
                "admin_include_all_for_an_admin",
                OrganizationMembership.Level.ADMIN,
                None,
                "admin_include_all=true",
                "session",
            ),
            (
                "admin_include_all_for_a_member",
                OrganizationMembership.Level.MEMBER,
                None,
                "admin_include_all=true",
                "session",
            ),
            ("personal_api_key", OrganizationMembership.Level.MEMBER, None, "", "personal_api_key"),
        ]
    )
    def test_list_shows_the_experiments_the_authorization_sdk_shows(
        self,
        _name: str,
        level: OrganizationMembership.Level,
        resource_access_level: str | None,
        query: str,
        credential: str,
    ) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()
        other_user = self._create_user("experiment-owner@posthog.com")
        self._experiment("Open", other_user)
        self._experiment("Blocked", other_user, "none")
        self._experiment("Granted", other_user, "viewer", member=self.organization_membership)
        self._experiment("Own blocked", self.user, "none")
        if resource_access_level is not None:
            create_access_control(team_id=self.team.id, resource="experiment", access_level=resource_access_level)

        sdk_names = self._names_the_sdk_shows(include_all_if_admin="admin_include_all=true" in query)

        assert self._listed_names(query, credential) == sdk_names
        # Every case hides "Blocked" or lists it only because of admin_include_all, so the comparison is not vacuous.
        assert ("Blocked" in sdk_names) == (level == OrganizationMembership.Level.ADMIN)

    def test_list_with_a_project_secret_api_key_shows_every_experiment(self) -> None:
        other_user = self._create_user("experiment-owner@posthog.com")
        self._experiment("Open", other_user)
        self._experiment("Blocked", other_user, "none")

        assert self._listed_names("", "project_secret_api_key") == {"Open", "Blocked"}
