from datetime import timedelta
from typing import Any

import pytest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.metric_calculation.config import ExperimentCalculationSettings
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentHoldout,
    build_rule_snapshot,
    get_experiment_rule,
)
from products.experiments.backend.temporal.canary_logic import _eligible_experiments
from products.feature_flags.backend.facade.rules import ExperimentRuleError
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest

RULE_A = "11111111-1111-4111-8111-111111111111"
RULE_B = "22222222-2222-4222-8222-222222222222"
RELEASE_RULE = "33333333-3333-4333-8333-333333333333"
UNKNOWN_RULE = "99999999-9999-4999-8999-999999999999"

CUSTOM_EXPOSURE = {"exposure_config": {"kind": "ExperimentEventExposureConfig", "event": "$pageview", "properties": []}}
ACTIVATION = {"activation_config": {"kind": "ExperimentEventExposureConfig", "event": "$pageview", "properties": []}}


def _experiment_rule(rule_id: str, *, weights: tuple[int, int] = (50, 50)) -> dict[str, Any]:
    return {
        "id": rule_id,
        "rule_type": "experiment",
        "targeting": {"properties": []},
        "paused": False,
        "rollout_percentage": 80,
        "on_rollout_miss": "continue",
        "assignment_algorithm": "sha1_60_v1",
        "seed": f"seed-{rule_id}",
        "variants": [
            {"key": "control", "weight": weights[0], "value": False},
            {"key": "test", "weight": weights[1], "value": True},
        ],
    }


def _v2_filters(*rules: dict[str, Any]) -> dict[str, Any]:
    return {"version": 2, "return_type": "boolean", "default_value": False, "rules": list(rules)}


class RuleLinkedExperimentTestCase(APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/experiments/"

    def _flag(self, key: str = "flag-with-rules", *rules: dict[str, Any], active: bool = True) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name=key,
            active=active,
            filters=_v2_filters(*(rules or (_experiment_rule(RULE_A),))),
        )

    def _create(self, flag_key: str = "flag-with-rules", **body: Any):
        return self.client.post(self.url, {"name": "On a rule", "feature_flag_key": flag_key, **body}, format="json")

    def _draft(self, flag: FeatureFlag | None = None, **body: Any) -> Experiment:
        flag = flag or self._flag()
        response = self._create(flag.key, **body)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return Experiment.objects.get(pk=response.json()["id"])

    def _launched(self, flag: FeatureFlag | None = None, **body: Any) -> Experiment:
        return self._launched_experiment(self._draft(flag, **body))

    def _launched_experiment(self, experiment: Experiment) -> Experiment:
        response = self.client.post(f"{self.url}{experiment.id}/launch/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return Experiment.objects.get(pk=experiment.pk)


class TestRuleLinkedCreate(RuleLinkedExperimentTestCase):
    def test_create_links_the_only_experiment_rule_and_leaves_the_flag(self) -> None:
        flag = self._flag("flag-with-rules", _experiment_rule(RULE_A, weights=(30, 70)), active=False)
        stored = (flag.filters, flag.version, flag.active)

        response = self._create()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["feature_flag_rule_id"] == RULE_A
        assert body["status"] == "draft"
        assert body["resolved_exposure_event"] == "$experiment_exposure"
        assert body["can_freeze_exposure"] is False
        assert body["parameters"] == {
            "feature_flag_variants": [
                {"key": "control", "rollout_percentage": 30, "split_percent": 30},
                {"key": "test", "rollout_percentage": 70, "split_percent": 70},
            ],
            "rollout_percentage": 80,
            "ensure_experience_continuity": False,
        }
        experiment = Experiment.objects.get(pk=body["id"])
        assert str(experiment.feature_flag_rule_id) == RULE_A
        assert experiment.feature_flag_rule_snapshot is None
        flag.refresh_from_db()
        assert (flag.filters, flag.version, flag.active) == stored

    def test_create_links_the_named_rule_of_a_flag_with_several(self) -> None:
        self._flag("flag-with-rules", _experiment_rule(RULE_A), _experiment_rule(RULE_B, weights=(10, 90)))

        response = self._create(feature_flag_rule_id=RULE_B)

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["feature_flag_rule_id"] == RULE_B
        assert [
            variant["rollout_percentage"] for variant in response.json()["parameters"]["feature_flag_variants"]
        ] == [
            10,
            90,
        ]

    @parameterized.expand(
        [
            (
                "several_rules_and_none_named",
                {},
                f"has 2 experiment rules. Name one with feature_flag_rule_id: {RULE_A}",
            ),
            ("unknown_rule", {"feature_flag_rule_id": UNKNOWN_RULE}, f"has no rule with the ID {UNKNOWN_RULE}"),
            ("release_rule", {"feature_flag_rule_id": RELEASE_RULE}, "is not an experiment rule"),
            ("web_experiment", {"feature_flag_rule_id": RULE_A, "type": "web"}, "A web experiment cannot run"),
            (
                "custom_exposure",
                {"feature_flag_rule_id": RULE_A, "exposure_criteria": CUSTOM_EXPOSURE},
                "custom exposure",
            ),
            ("activation", {"feature_flag_rule_id": RULE_A, "exposure_criteria": ACTIVATION}, "activation event"),
            (
                "start_date",
                {"feature_flag_rule_id": RULE_A, "start_date": "2026-01-01T00:00:00Z"},
                "Create it as a draft, then launch it",
            ),
        ]
    )
    def test_create_refuses(self, _name: str, body: dict[str, Any], message: str) -> None:
        self._flag(
            "flag-with-rules",
            _experiment_rule(RULE_A),
            _experiment_rule(RULE_B),
            {"id": RELEASE_RULE, "rule_type": "targeted_release", "targeting": {"properties": []}, "value": True},
        )

        response = self._create(**body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert message in response.json()["detail"]
        assert not Experiment.objects.filter(team=self.team).exists()

    def test_create_refuses_a_shared_holdout(self) -> None:
        self._flag()
        holdout = ExperimentHoldout.objects.create(
            team=self.team, name="Holdout", filters=[{"properties": [], "rollout_percentage": 10}]
        )

        response = self._create(holdout_id=holdout.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Set the holdout on the rule instead" in response.json()["detail"]

    def test_create_refuses_a_flag_without_an_experiment_rule(self) -> None:
        self._flag(
            "flag-with-rules",
            {"id": RELEASE_RULE, "rule_type": "targeted_release", "targeting": {"properties": []}, "value": True},
        )

        response = self._create()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "has no experiment rule" in response.json()["detail"]

    @parameterized.expand(
        [
            ("flag_without_rules", "legacy-flag", "has no rules"),
            ("flag_that_does_not_exist", "new-flag", "no feature flag has the key new-flag"),
        ]
    )
    def test_a_rule_id_needs_a_flag_with_rules(self, _name: str, flag_key: str, message: str) -> None:
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="legacy-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        response = self._create(flag_key, feature_flag_rule_id=RULE_A)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert message in response.json()["detail"]
        assert not FeatureFlag.objects.filter(team=self.team, key="new-flag").exists()

    @parameterized.expand([("live",), ("deleted",)])
    def test_a_rule_runs_one_experiment(self, holder_state: str) -> None:
        holder = self._draft()
        if holder_state == "deleted":
            Experiment.objects.filter(pk=holder.pk).update(deleted=True)

        response = self._create(name="Second on the same rule")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert f"already belongs to experiment {holder.id}" in response.json()["detail"]

    def test_a_legacy_experiment_has_no_rule(self) -> None:
        response = self._create("brand-new-flag")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["feature_flag_rule_id"] is None
        assert response.json()["resolved_exposure_event"] != ""
        assert Experiment.objects.get(pk=response.json()["id"]).feature_flag_rule_snapshot is None


class TestRuleLinkedLaunch(RuleLinkedExperimentTestCase):
    def test_launch_stores_the_snapshot_and_leaves_the_flag(self) -> None:
        flag = self._flag(active=False)
        experiment = self._draft(flag)
        stored = (flag.filters, flag.version, flag.active)

        response = self.client.post(f"{self.url}{experiment.id}/launch/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        experiment.refresh_from_db()
        flag.refresh_from_db()
        assert experiment.start_date is not None
        assert experiment.feature_flag_rule_snapshot == {
            "flag": {
                "id": flag.id,
                "key": "flag-with-rules",
                "version": flag.version,
                "return_type": "boolean",
                "default_value": False,
                "aggregation_group_type_index": None,
            },
            "rule": _experiment_rule(RULE_A),
        }
        assert (flag.filters, flag.version, flag.active) == stored
        assert response.json()["status"] == "paused"
        launch_log = ActivityLog.objects.get(scope="Experiment", item_id=str(experiment.id), activity="updated")
        assert launch_log.detail is not None
        logged_fields = {change["field"] for change in launch_log.detail["changes"]}
        assert "start_date" in logged_fields
        assert "feature_flag_rule_snapshot" not in logged_fields

    def test_launch_snapshots_the_rule_as_it_is_at_the_launch(self) -> None:
        flag = self._flag()
        experiment = self._draft(flag)
        flag.filters = _v2_filters(_experiment_rule(RULE_A, weights=(20, 80)))
        flag.save()

        response = self.client.post(f"{self.url}{experiment.id}/launch/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        experiment.refresh_from_db()
        snapshot = experiment.feature_flag_rule_snapshot
        assert snapshot is not None
        assert [variant["weight"] for variant in snapshot["rule"]["variants"]] == [20, 80]

    @parameterized.expand(
        [
            ("rule_removed", _v2_filters(), "has no rule with the ID"),
            (
                "rule_became_a_release",
                _v2_filters(
                    {"id": RULE_A, "rule_type": "targeted_release", "targeting": {"properties": []}, "value": True}
                ),
                "is not an experiment rule",
            ),
        ]
    )
    def test_launch_refuses_a_rule_that_is_gone(self, _name: str, later_filters: dict[str, Any], message: str) -> None:
        flag = self._flag()
        experiment = self._draft(flag)
        flag.filters = later_filters
        flag.save()

        response = self.client.post(f"{self.url}{experiment.id}/launch/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert message in response.json()["detail"]
        experiment.refresh_from_db()
        assert experiment.start_date is None
        assert experiment.feature_flag_rule_snapshot is None

    def test_a_launch_that_lost_a_race_keeps_the_first_snapshot(self) -> None:
        flag = self._flag()
        experiment = self._draft(flag)
        read_as_a_draft = Experiment.objects.get(pk=experiment.pk)
        launched = self._launched_experiment(experiment)
        flag.filters = _v2_filters(_experiment_rule(RULE_A, weights=(20, 80)))
        flag.save()

        with pytest.raises(ValidationError, match="already been launched"):
            ExperimentService(team=self.team, user=self.user).launch_experiment(read_as_a_draft)

        experiment.refresh_from_db()
        assert experiment.start_date == launched.start_date
        snapshot = experiment.feature_flag_rule_snapshot
        assert snapshot is not None and snapshot == launched.feature_flag_rule_snapshot
        assert [variant["weight"] for variant in snapshot["rule"]["variants"]] == [50, 50]

    def test_launch_refuses_variants_that_changed_after_its_checks(self) -> None:
        flag = self._flag()
        experiment = self._draft(flag)
        with_the_flag_as_checked = Experiment.objects.select_related("feature_flag").get(pk=experiment.pk)
        renamed_variant = _experiment_rule(RULE_A)
        renamed_variant["variants"][0]["key"] = "baseline"
        FeatureFlag.objects.filter(pk=flag.pk).update(filters=_v2_filters(renamed_variant))

        with pytest.raises(ValidationError, match="changed during the launch"):
            ExperimentService(team=self.team, user=self.user).launch_experiment(with_the_flag_as_checked)

        experiment.refresh_from_db()
        assert experiment.start_date is None
        assert experiment.feature_flag_rule_snapshot is None

    def test_a_started_experiment_keeps_the_flag_key_of_its_launch(self) -> None:
        flag = self._flag()
        started = self._launched(flag)
        draft = self._draft(self._flag("another-flag", _experiment_rule(RULE_B)))
        flag.key = "renamed-flag"
        flag.save()
        FeatureFlag.objects.filter(pk=draft.feature_flag_id).update(key="another-renamed-flag")

        started, draft = (Experiment.objects.get(pk=experiment.pk) for experiment in (started, draft))

        assert get_experiment_rule(started).flag_key == "flag-with-rules"
        assert ExperimentCalculationSettings.from_experiment(started).feature_flag_key == "flag-with-rules"
        assert ExperimentCalculationSettings.from_experiment(draft).feature_flag_key == "another-renamed-flag"

    def test_a_started_experiment_reads_its_snapshot_after_the_rule_is_removed(self) -> None:
        flag = self._flag("flag-with-rules", _experiment_rule(RULE_A, weights=(30, 70)))
        experiment = self._launched(flag)
        flag.filters = _v2_filters()
        flag.save()

        retrieved = self.client.get(f"{self.url}{experiment.id}/")
        listed = self.client.get(self.url)

        assert retrieved.status_code == status.HTTP_200_OK, retrieved.json()
        assert listed.status_code == status.HTTP_200_OK, listed.json()
        for body in (retrieved.json(), listed.json()["results"][0]):
            assert [variant["rollout_percentage"] for variant in body["parameters"]["feature_flag_variants"]] == [
                30,
                70,
            ]
        experiment.refresh_from_db()
        assert ExperimentCalculationSettings.from_experiment(experiment).variants == ("control", "test")

    def test_a_draft_whose_rule_is_gone_still_reads(self) -> None:
        flag = self._flag()
        experiment = self._draft(flag)
        flag.filters = _v2_filters()
        flag.save()

        retrieved = self.client.get(f"{self.url}{experiment.id}/")
        listed = self.client.get(self.url)

        assert retrieved.status_code == status.HTTP_200_OK, retrieved.json()
        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert retrieved.json()["parameters"]["feature_flag_variants"] == []
        experiment.refresh_from_db()
        with pytest.raises(ExperimentRuleError):
            get_experiment_rule(experiment)
        # The settings of every experiment are built in one pass, so one unreadable rule must not raise.
        assert ExperimentCalculationSettings.from_experiment(experiment).variants == ()

    def test_no_write_starts_an_experiment_without_its_snapshot(self) -> None:
        experiment = self._draft()
        experiment.start_date = timezone.now()

        with pytest.raises(ValueError, match="cannot start without its rule snapshot"):
            experiment.save()

    def test_end_keeps_the_flag_and_the_snapshot(self) -> None:
        flag = self._flag()
        experiment = self._launched(flag)
        snapshot = experiment.feature_flag_rule_snapshot
        stored = (flag.filters, flag.version, flag.active)

        response = self.client.post(f"{self.url}{experiment.id}/end/", {"conclusion": "won"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        experiment.refresh_from_db()
        flag.refresh_from_db()
        assert experiment.end_date is not None
        assert experiment.feature_flag_rule_snapshot == snapshot
        assert (flag.filters, flag.version, flag.active) == stored


class TestRuleLinkedRefusals(RuleLinkedExperimentTestCase):
    @parameterized.expand(
        [
            ("pause", "pause", {}, "pausing is not supported"),
            ("ship_variant", "ship_variant", {"variant_key": "test"}, "shipping a variant is not supported"),
            ("reset", "reset", {}, "resetting is not supported"),
            ("duplicate", "duplicate", {}, "duplicating or copying it is not supported"),
            ("freeze_exposure", "freeze_exposure", {}, "cannot have their exposure frozen yet"),
            (
                "exposure_cohort",
                "create_exposure_cohort_for_experiment",
                {},
                "creating an exposure cohort is not supported",
            ),
        ]
    )
    def test_actions_that_write_or_read_a_legacy_flag_are_refused(
        self, _name: str, action: str, body: dict[str, Any], message: str
    ) -> None:
        flag = self._flag()
        experiment = self._launched(flag)
        stored = (flag.filters, flag.version, flag.active)

        response = self.client.post(f"{self.url}{experiment.id}/{action}/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert message in response.json()["detail"]
        flag.refresh_from_db()
        assert (flag.filters, flag.version, flag.active) == stored

    def test_resume_is_refused(self) -> None:
        experiment = self._launched(self._flag(active=False))

        response = self.client.post(f"{self.url}{experiment.id}/resume/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "resuming is not supported" in response.json()["detail"]
        assert not FeatureFlag.objects.get(pk=experiment.feature_flag_id).active

    @parameterized.expand(
        [
            (
                "flag_config",
                {
                    "feature_flag": {
                        "filters": {
                            "multivariate": {
                                "variants": [
                                    {"key": "control", "rollout_percentage": 50},
                                    {"key": "test", "rollout_percentage": 50},
                                ]
                            }
                        }
                    },
                    "update_feature_flag_params": True,
                },
                "changing the flag config from the experiment is not supported",
            ),
            ("custom_exposure", {"exposure_criteria": CUSTOM_EXPOSURE}, "custom exposure"),
            ("clearing_the_start_date", {"start_date": None}, "clearing the start date is not supported"),
            ("another_rule", {"feature_flag_rule_id": RULE_B}, "feature_flag_rule_id cannot change"),
        ]
    )
    def test_updates_of_a_started_experiment_that_are_refused(
        self, _name: str, body: dict[str, Any], message: str
    ) -> None:
        flag = self._flag("flag-with-rules", _experiment_rule(RULE_A), _experiment_rule(RULE_B))
        experiment = self._launched(flag, feature_flag_rule_id=RULE_A)
        stored = flag.filters

        response = self.client.patch(f"{self.url}{experiment.id}/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert message in str(response.json())
        flag.refresh_from_db()
        experiment.refresh_from_db()
        assert flag.filters == stored
        assert str(experiment.feature_flag_rule_id) == RULE_A
        assert experiment.start_date is not None

    def test_a_start_date_does_not_launch_a_draft(self) -> None:
        experiment = self._draft()

        response = self.client.patch(
            f"{self.url}{experiment.id}/", {"start_date": "2026-01-01T00:00:00Z"}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "starts with the launch action" in response.json()["detail"]
        experiment.refresh_from_db()
        assert experiment.start_date is None

    def test_an_update_that_sends_back_what_it_read_changes_the_experiment_only(self) -> None:
        flag = self._flag()
        experiment = self._launched(flag)
        stored = (flag.filters, flag.version)
        read = self.client.get(f"{self.url}{experiment.id}/").json()

        response = self.client.patch(
            f"{self.url}{experiment.id}/",
            {
                "name": "Renamed",
                "parameters": read["parameters"],
                "feature_flag_rule_id": read["feature_flag_rule_id"],
                "start_date": (timezone.now() - timedelta(days=2)).isoformat(),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "Renamed"
        flag.refresh_from_db()
        assert (flag.filters, flag.version) == stored

    def test_a_legacy_experiment_cannot_be_duplicated_onto_a_flag_with_rules(self) -> None:
        self._flag("flag-with-rules")
        legacy = Experiment.objects.get(pk=self._create("legacy-flag").json()["id"])

        response = self.client.post(
            f"{self.url}{legacy.id}/duplicate/", {"feature_flag_key": "flag-with-rules"}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "configuration format" in str(response.json())


class TestRuleLinkedBackgroundReads(RuleLinkedExperimentTestCase):
    def test_canary_sampling_leaves_out_rule_linked_experiments(self) -> None:
        flag = self._flag()
        experiment = self._launched(flag)
        Experiment.objects.filter(pk=experiment.pk).update(start_date=timezone.now() - timedelta(days=30))
        legacy = Experiment.objects.get(pk=self._create("legacy-flag").json()["id"])
        Experiment.objects.filter(pk=legacy.pk).update(start_date=timezone.now() - timedelta(days=30))
        with patch(
            "products.experiments.backend.temporal.canary_logic.TeamExperimentsConfig.objects.filter"
        ) as config_filter:
            config_filter.return_value.values_list.return_value = [self.team.id]

            eligible = _eligible_experiments()

        assert [candidate.id for candidate in eligible] == [legacy.id]

    def test_snapshot_reader_matches_the_rule_as_stored(self) -> None:
        flag = self._flag("flag-with-rules", _experiment_rule(RULE_A, weights=(30, 70)))

        snapshot = build_rule_snapshot(flag, RULE_A.upper())

        assert snapshot["rule"] == _experiment_rule(RULE_A, weights=(30, 70))
