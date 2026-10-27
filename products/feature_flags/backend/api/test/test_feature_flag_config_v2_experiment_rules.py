import copy
from collections.abc import Callable
from typing import Any

from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.api.test.test_feature_flag_config_v2_updates import (
    HOLDOUT_SEED_C,
    RULE_B,
    RULE_C,
    RULE_VALUE_DETAIL,
    SEED_B,
    SEED_C,
    AdmittedV2TestCase,
    admit_v2,
    config,
    experiment,
    local_holdout,
    rollout,
    targeted,
)
from products.feature_flags.backend.flags_cache import _get_feature_flags_for_service
from products.feature_flags.backend.models import FeatureFlag


def string_split(first: str, **extra: Any) -> dict:
    variants = [{"key": "a", "weight": 50, "value": first}, {"key": "b", "weight": 50, "value": "on"}]
    return config(experiment(variants=variants, **extra), return_type="string", default_value=None)


NULL_KEY_DETAIL = 'The variant key "null" is reserved. Choose another key.'
NULL_KEY_ATTR = "filters__rules__0__variants__0__key"


def keyed_split(first_key: str, return_type: str = "boolean", **extra: Any) -> dict:
    off, on = {"boolean": (False, True), "string": ("off", "on")}[return_type]
    variants = [{"key": first_key, "weight": 50, "value": off}, {"key": "test", "weight": 50, "value": on}]
    return config(experiment(variants=variants, **extra), return_type=return_type, default_value=None)


class TestExperimentRules(AdmittedV2TestCase):
    def test_create_assigns_the_rule_and_holdout_seeds(self) -> None:
        submitted = config(
            targeted(rule_id=None), experiment(rule_id=None, seed=None, holdout=local_holdout(seed=None))
        )
        with admit_v2(self.team.id, creation=True):
            response = self.post_flag({"key": "split-v2", "filters": submitted})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flag = FeatureFlag.objects.get(team=self.team, key="split-v2")
        rule = flag.filters["rules"][1]
        assert rule["id"] and rule["seed"] and rule["holdout"]["seed"]
        assert len({rule["seed"], rule["holdout"]["seed"]}) == 2
        assert "experiment_id" not in rule and set(rule["holdout"]) == {"seed", "exclusion_percentage"}
        assert not Experiment.objects.filter(feature_flag=flag).exists()
        assert response.json()["filters"] == flag.filters

    def test_seeds_survive_reorder_and_unrelated_edits(self) -> None:
        flag = self.flag(config(targeted(), experiment(holdout=local_holdout())))
        replacement = config(
            experiment(seed=None, holdout=local_holdout(seed=None, exclusion_percentage=25), paused=True),
            targeted(value=False),
        )
        response = self.patch_flag(flag, {"version": 3, "filters": replacement})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        rule = flag.filters["rules"][0]
        assert (rule["id"], rule["seed"], rule["holdout"]["seed"]) == (RULE_C, SEED_C, HOLDOUT_SEED_C)
        assert (rule["paused"], rule["holdout"]["exclusion_percentage"]) == (True, 25)

    def test_a_percentage_rollout_that_becomes_an_experiment_rule_keeps_its_seed(self) -> None:
        flag = self.flag(config(rollout()))
        response = self.patch_flag(flag, {"version": 3, "filters": config(experiment(rule_id=RULE_B, seed=None))})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters["rules"][0]["seed"] == SEED_B

    def test_a_holdout_added_later_gets_a_fresh_seed(self) -> None:
        flag = self.flag(config(experiment()))
        response = self.patch_flag(
            flag, {"version": 3, "filters": config(experiment(holdout=local_holdout(seed=None)))}
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters["rules"][0]["holdout"]["seed"] not in (None, "", SEED_C, HOLDOUT_SEED_C)

    @parameterized.expand(
        [
            (
                "changed_holdout_seed",
                config(experiment(holdout=local_holdout(seed="chosen-by-client"))),
                "filters__rules__0__holdout__seed",
            ),
            ("chosen_seed", config(experiment(rule_id=None, seed="chosen-by-client")), "filters__rules__0__seed"),
            (
                "chosen_holdout_seed",
                config(experiment(rule_id=None, seed=None, holdout=local_holdout(seed="chosen"))),
                "filters__rules__0__holdout__seed",
            ),
        ]
    )
    def test_invalid_rules_are_rejected(self, _name: str, filters: dict, attr: str) -> None:
        flag = self.flag(config(experiment(holdout=local_holdout())))
        stored = copy.deepcopy(flag.filters)
        response = self.patch_flag(flag, {"version": 3, "filters": filters})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == attr, response.json()
        flag.refresh_from_db()
        assert (flag.filters, flag.version) == (stored, 3)

    @parameterized.expand(
        [
            ("experiment_id", experiment(experiment_id=42), "filters.rules[0].experiment_id"),
            ("null_experiment_id", experiment(experiment_id=None), "filters.rules[0].experiment_id"),
            ("holdout_id", experiment(holdout={**local_holdout(), "id": 7}), "filters.rules[0].holdout.id"),
            ("null_holdout_id", experiment(holdout={**local_holdout(), "id": None}), "filters.rules[0].holdout.id"),
            # Reported as the unknown field, not as a client-chosen holdout seed.
            ("rollout_holdout", rollout(rule_id=None, seed=None, holdout=local_holdout()), "filters.rules[0].holdout"),
        ]
    )
    def test_ids_and_misplaced_holdouts_are_unknown_fields(self, _name: str, rule: dict, path: str) -> None:
        flag = self.flag(config(experiment(holdout=local_holdout())))
        stored = copy.deepcopy(flag.filters)
        response = self.patch_flag(flag, {"version": 3, "filters": config(rule)})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "unknown_field",
            "detail": f"{path}: Unknown field.",
            "attr": "filters",
        }
        flag.refresh_from_db()
        assert (flag.filters, flag.version) == (stored, 3)

    def test_create_rejects_a_null_experiment_id(self) -> None:
        submitted = config(experiment(rule_id=None, seed=None, experiment_id=None))
        with admit_v2(self.team.id, creation=True):
            response = self.post_flag({"key": "split-v2", "filters": submitted})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "filters.rules[0].experiment_id: Unknown field.", response.json()
        assert not FeatureFlag.objects.filter(team=self.team, key="split-v2").exists()

    @parameterized.expand([("false", "$false"), ("true", "$true"), ("null", "null")])
    def test_reserved_strings_are_rejected_as_variant_values(self, _name: str, value: str) -> None:
        flag = self.flag(string_split("off"))
        response = self.patch_flag(flag, {"version": 3, "filters": string_split(value)})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert (body["attr"], body["detail"]) == ("filters__rules__0__variants__0__value", RULE_VALUE_DETAIL), body
        flag.refresh_from_db()
        assert (flag.filters, flag.version) == (string_split("off"), 3)

    @parameterized.expand([("variant_value", string_split), ("variant_key", keyed_split)])
    def test_a_null_variant_the_rule_already_holds_is_kept_and_can_be_enabled(
        self, _name: str, split: Callable[..., dict]
    ) -> None:
        flag = self.flag(split("null"), active=False)
        replacement = split("null", paused=True)
        response = self.patch_flag(flag, {"version": 3, "filters": replacement})
        assert response.status_code == status.HTTP_200_OK, response.json()
        response = self.patch_flag(flag, {"version": 4, "active": True})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert (flag.filters, flag.active, flag.version) == (replacement, True, 5)

    @parameterized.expand([("boolean",), ("string",)])
    def test_create_rejects_a_null_variant_key(self, return_type: str) -> None:
        with admit_v2(self.team.id, creation=True):
            submitted = keyed_split("null", return_type, rule_id=None, seed=None)
            response = self.post_flag({"key": "split-v2", "filters": submitted})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert (body["code"], body["attr"], body["detail"]) == ("invalid_input", NULL_KEY_ATTR, NULL_KEY_DETAIL)
        assert not FeatureFlag.objects.filter(team=self.team, key="split-v2").exists()

    @parameterized.expand(
        [
            ("boolean", keyed_split("control"), keyed_split("null"), NULL_KEY_ATTR),
            ("string", keyed_split("control", "string"), keyed_split("null", "string"), NULL_KEY_ATTR),
            (
                # A held key stays with its rule's experiment, so a new rule cannot take it over.
                "held_by_another_rule",
                keyed_split("null"),
                config(
                    *keyed_split("control")["rules"],
                    *keyed_split("null", rule_id=None, seed=None)["rules"],
                    default_value=None,
                ),
                "filters__rules__1__variants__0__key",
            ),
        ]
    )
    def test_update_rejects_a_new_null_variant_key(self, _name: str, stored: dict, submitted: dict, attr: str) -> None:
        flag = self.flag(stored)
        response = self.patch_flag(flag, {"version": 3, "filters": submitted})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert (body["code"], body["attr"], body["detail"]) == ("invalid_input", attr, NULL_KEY_DETAIL)
        flag.refresh_from_db()
        assert (flag.filters, flag.version) == (stored, 3)

    def test_a_split_above_a_lower_rule_reports_warnings_and_is_cached(self) -> None:
        flag = self.flag(config(experiment()), active=True)
        # A 100% split with no holdout returns a value for everyone, so the targeted rule below is never reached.
        document = config(experiment(), targeted(rule_id=None))
        with patch("products.feature_flags.backend.api.feature_flag.logger.info") as info:
            response = self.patch_flag(flag, {"version": 3, "filters": document})
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert info.call_args.kwargs["extra"]["codes"] == ["UNREACHABLE_LOWER_RULE"]
        cached = {f["key"]: f for f in _get_feature_flags_for_service(self.team)["flags"]}
        assert cached[flag.key]["filters"]["rules"][0]["seed"] == SEED_C
