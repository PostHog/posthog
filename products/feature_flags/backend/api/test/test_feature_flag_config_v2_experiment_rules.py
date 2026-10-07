"""Config version 2 experiment rules without an experiment: identity, admission and warnings through the API.

These flags are invented test rows.
"""

import copy

from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.api.test.test_feature_flag_config_v2_updates import (
    HOLDOUT_SEED_C,
    RULE_B,
    RULE_C,
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


class TestStandaloneExperimentRules(AdmittedV2TestCase):
    """Experiment rules without an experiment: no Experiment row, server-owned seeds, the shared validator's limits."""

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
        assert (rule["experiment_id"], rule["holdout"]["id"]) == (None, None)
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
                "filters.rules[0].holdout.seed",
            ),
            ("chosen_seed", config(experiment(rule_id=None, seed="chosen-by-client")), "filters.rules[0].seed"),
            (
                "chosen_holdout_seed",
                config(experiment(rule_id=None, seed=None, holdout=local_holdout(seed="chosen"))),
                "filters.rules[0].holdout.seed",
            ),
            ("shared_holdout", config(experiment(holdout={**local_holdout(), "id": 7})), "filters.rules[0].holdout.id"),
        ]
    )
    def test_invalid_rules_are_rejected(self, _name: str, filters: dict, attr: str) -> None:
        flag = self.flag(config(experiment(holdout=local_holdout())))
        stored = copy.deepcopy(flag.filters)
        response = self.patch_flag(flag, {"version": 3, "filters": filters})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"].startswith(f"{attr}: "), response.json()
        flag.refresh_from_db()
        assert (flag.filters, flag.version) == (stored, 3)

    def test_reserved_strings_are_rejected_as_variant_values(self) -> None:
        def string_split(first: str) -> dict:
            variants = [{"key": "a", "weight": 50, "value": first}, {"key": "b", "weight": 50, "value": "on"}]
            return config(experiment(variants=variants), return_type="string", default_value=None)

        flag = self.flag(string_split("off"))
        response = self.patch_flag(flag, {"version": 3, "filters": string_split("$false")})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"].startswith("filters.rules[0].variants[0].value: "), response.json()

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
