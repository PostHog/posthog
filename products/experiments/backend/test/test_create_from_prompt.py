import json
from collections.abc import Callable
from typing import Any

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.facade.api import get_evaluation_pass_filters
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.llm_prompt import LLMPrompt
from products.experiments.backend.llm_metric_templates import TEMPLATE_NAMES, rebuild_eval_pass_rate_metrics
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest


def _split_distribution(variants: list[dict[str, Any]]) -> list[int]:
    return [v["rollout_percentage"] for v in variants]


def _expected_splits(n: int) -> list[int]:
    base = 100 // n
    splits = [base] * n
    splits[-1] += 100 - base * n
    return splits


def _use_legacy_sources(experiment: Experiment, *, with_result_type: bool = False) -> None:
    assert experiment.metrics is not None and experiment.parameters is not None
    prompt_name = experiment.parameters["prompt_metadata"]["name"]
    experiment.parameters["prompt_metadata"].pop("eval_pass_rate_sources")
    prompt_filter = {"key": "$ai_prompt_name", "type": "event", "value": prompt_name, "operator": "exact"}
    applicable = {"key": "JSONExtractRaw(properties, '$ai_evaluation_applicable') != 'false'", "type": "hogql"}
    result = {"key": "JSONExtractBool(properties, '$ai_evaluation_result')", "type": "hogql"}
    boolean_only = (
        [{"key": "JSONExtractString(properties, '$ai_evaluation_result_type') IN ('', 'boolean')", "type": "hogql"}]
        if with_result_type
        else []
    )
    experiment.metrics[1]["numerator"] = {
        "kind": "EventsNode",
        "event": "$ai_evaluation",
        "properties": [prompt_filter, result, applicable, *boolean_only],
    }
    experiment.metrics[1]["denominator"] = {
        "kind": "EventsNode",
        "event": "$ai_evaluation",
        "properties": [prompt_filter, applicable, *boolean_only],
    }


class TestExperimentsCreateFromPrompt(APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        self.prompt_name = "my-prompt"
        for version in (1, 2, 3, 4, 5):
            LLMPrompt.objects.create(
                team=self.team,
                created_by=self.user,
                name=self.prompt_name,
                prompt={"text": f"Prompt v{version}"},
                version=version,
                is_latest=(version == 5),
            )

    def _post(self, **overrides: Any) -> Any:
        payload: dict[str, Any] = {
            "prompt_name": self.prompt_name,
            "versions": [1, 2],
            "templates": ["cost"],
        }
        payload.update(overrides)
        return self.client.post(
            f"/api/projects/{self.team.id}/experiments/create_from_prompt/",
            payload,
            format="json",
        )

    def test_url_under_prompt_templates(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/prompt_templates/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        keys = [t["key"] for t in body]
        self.assertEqual(set(keys), set(TEMPLATE_NAMES))
        for entry in body:
            self.assertIn("label", entry)
            self.assertIn("description", entry)

    @parameterized.expand(
        [(name, n) for name in TEMPLATE_NAMES for n in (2, 3, 5)],
        name_func=lambda fn, _i, p: f"{fn.__name__}_{p.args[0]}_n{p.args[1]}",
    )
    def test_happy_path(self, template_name: str, n: int) -> None:
        versions = list(range(1, n + 1))
        response = self._post(templates=[template_name], versions=versions)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        body = response.json()

        experiment = Experiment.objects.get(pk=body["id"])
        self.assertEqual(experiment.team_id, self.team.id)
        self.assertTrue(experiment.is_draft)
        assert experiment.parameters is not None
        assert experiment.metrics is not None

        # parameters.prompt_metadata round-trips
        prompt_metadata = experiment.parameters["prompt_metadata"]
        self.assertEqual(prompt_metadata["name"], self.prompt_name)
        self.assertEqual(prompt_metadata["templates"], [template_name])
        self.assertEqual(prompt_metadata["versions"], versions)

        # Variant split distribution sums to 100 with the right shape. The flag is the source of
        # truth for variants (parameters no longer mirrors them).
        feature_flag = FeatureFlag.objects.get(key=experiment.feature_flag.key, team_id=self.team.id)
        variants = feature_flag.filters["multivariate"]["variants"]
        self.assertEqual(len(variants), n)
        self.assertEqual(sum(_split_distribution(variants)), 100)
        self.assertEqual(_split_distribution(variants), _expected_splits(n))

        # Variant key naming: control + test (2-variant) or test-i (N>=3); names use v{version}
        self.assertEqual(variants[0]["key"], "control")
        self.assertEqual(variants[0]["name"], f"v{versions[0]}")
        for i, variant in enumerate(variants[1:], start=1):
            expected_key = "test" if n == 2 else f"test-{i}"
            self.assertEqual(variant["key"], expected_key)
            self.assertEqual(variant["name"], f"v{versions[i]}")

        # Each variant carries a JSON payload with {prompt_name, prompt_version} so the SDK can
        # read it via flags.get_flag_payload(...) without consulting any other state.
        payloads = feature_flag.filters["payloads"]
        self.assertEqual(set(payloads.keys()), {v["key"] for v in variants})
        for variant, version in zip(variants, versions):
            decoded = json.loads(payloads[variant["key"]])
            self.assertEqual(decoded, {"prompt_name": self.prompt_name, "prompt_version": version})

        # Single primary metric, scoped to $ai_prompt_name = self.prompt_name
        self.assertEqual(len(experiment.metrics), 1)
        metric = experiment.metrics[0]
        self.assertEqual(metric["kind"], "ExperimentMetric")
        source_or_numerator = metric.get("source") or metric.get("numerator")
        assert source_or_numerator is not None, f"metric had neither source nor numerator: {metric}"
        properties = source_or_numerator["properties"]
        prompt_filter = next(p for p in properties if p.get("key") == "$ai_prompt_name")
        self.assertEqual(prompt_filter["value"], self.prompt_name)
        if template_name == "eval_pass_rate":
            pass_filters = get_evaluation_pass_filters(self.team.id)
            self.assertIn(pass_filters.passed, [prop["key"] for prop in metric["numerator"]["properties"]])
            self.assertIn(pass_filters.graded, [prop["key"] for prop in metric["denominator"]["properties"]])

    def _create_detector_evaluation(self) -> None:
        Evaluation.objects.create(
            team=self.team,
            name="Detector",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={"true_is_failure": True},
        )

    @parameterized.expand(
        [
            ("renamed", lambda e: e.metrics[1].update(name="My pass rate"), True),
            ("legacy template sources", _use_legacy_sources, True),
            (
                "legacy template sources with the result type filter",
                lambda e: _use_legacy_sources(e, with_result_type=True),
                True,
            ),
            ("deleted", lambda e: setattr(e, "deleted", True), False),
            ("ended", lambda e: setattr(e, "end_date", e.created_at), False),
            (
                "user added an event filter",
                lambda e: e.metrics[1]["numerator"]["properties"].append(
                    {"key": "$browser", "type": "event", "value": "Chrome", "operator": "exact"}
                ),
                False,
            ),
            ("user changed the aggregation", lambda e: e.metrics[1]["numerator"].update(math="dau"), False),
            (
                "user replaced a filter",
                lambda e: e.metrics[1]["denominator"]["properties"].__setitem__(
                    slice(1, None), [{"key": "properties.$ai_model = 'gpt-5'", "type": "hogql"}]
                ),
                False,
            ),
        ]
    )
    def test_evaluation_output_change_rebuilds_template_eval_pass_rate_metric(
        self, _name: str, change: Callable[[Experiment], None], rebuilds: bool
    ) -> None:
        response = self._post(templates=["cost", "eval_pass_rate"])
        experiment = Experiment.objects.get(pk=response.json()["id"])
        assert experiment.metrics is not None
        change(experiment)
        experiment.save()
        before = experiment.metrics
        version_before = experiment.version or 0

        with self.captureOnCommitCallbacks(execute=True):
            self._create_detector_evaluation()

        experiment.refresh_from_db()
        if not rebuilds:
            self.assertEqual(experiment.metrics, before)
            return
        assert experiment.metrics is not None
        pass_filters = get_evaluation_pass_filters(self.team.id)
        cost, pass_rate = experiment.metrics
        self.assertEqual(cost, before[0])
        self.assertEqual(pass_rate["name"], before[1]["name"])
        self.assertEqual(pass_rate["uuid"], before[1]["uuid"])
        self.assertNotEqual(pass_rate["fingerprint"], before[1]["fingerprint"])
        self.assertEqual(experiment.version, version_before + 1)
        self.assertIn(pass_filters.passed, [prop["key"] for prop in pass_rate["numerator"]["properties"]])
        self.assertIn(pass_filters.graded, [prop["key"] for prop in pass_rate["denominator"]["properties"]])
        self.assertEqual(rebuild_eval_pass_rate_metrics(self.team.id), 0)

    def test_rebuild_follows_a_metric_moved_to_secondary(self) -> None:
        experiment = Experiment.objects.get(pk=self._post(templates=["cost", "eval_pass_rate"]).json()["id"])
        assert experiment.metrics is not None
        experiment.metrics_secondary = [experiment.metrics.pop(1)]
        experiment.save()
        moved = experiment.metrics_secondary[0]

        with self.captureOnCommitCallbacks(execute=True):
            self._create_detector_evaluation()

        experiment.refresh_from_db()
        assert experiment.metrics_secondary is not None
        pass_filters = get_evaluation_pass_filters(self.team.id)
        rebuilt = experiment.metrics_secondary[0]
        self.assertEqual(rebuilt["uuid"], moved["uuid"])
        self.assertIn(pass_filters.passed, [prop["key"] for prop in rebuilt["numerator"]["properties"]])

    def test_multiple_templates_creates_one_metric_each(self) -> None:
        # Pick all available templates so we exercise both mean and ratio shapes.
        templates = list(TEMPLATE_NAMES)
        response = self._post(templates=templates)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        experiment = Experiment.objects.get(pk=response.json()["id"])
        assert experiment.parameters is not None
        assert experiment.metrics is not None
        self.assertEqual(experiment.parameters["prompt_metadata"]["templates"], templates)

        # One metric per template, in the same order, each scoped to the prompt.
        self.assertEqual(len(experiment.metrics), len(templates))
        for metric in experiment.metrics:
            source_or_numerator = metric.get("source") or metric.get("numerator")
            assert source_or_numerator is not None
            prompt_filter = next(p for p in source_or_numerator["properties"] if p.get("key") == "$ai_prompt_name")
            self.assertEqual(prompt_filter["value"], self.prompt_name)

    def test_uses_provided_name_and_feature_flag_key(self) -> None:
        response = self._post(name="My custom name", feature_flag_key="my-custom-key")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        experiment = Experiment.objects.get(pk=response.json()["id"])
        self.assertEqual(experiment.name, "My custom name")
        self.assertEqual(experiment.feature_flag.key, "my-custom-key")

    def test_400_when_feature_flag_key_already_exists(self) -> None:
        # Pre-create a flag with the key the caller will try to claim. Reusing it would skip
        # the payload-writing path in ExperimentService and yield a broken experiment.
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="taken-key", name="Existing")

        response = self._post(feature_flag_key="taken-key")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("feature_flag_key", str(response.json()))
        self.assertFalse(
            Experiment.objects.filter(team_id=self.team.id, feature_flag__key="taken-key").exists(),
        )

    def test_default_name_includes_versions_and_templates(self) -> None:
        response = self._post(versions=[2, 4], templates=["latency", "cost"])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        experiment = Experiment.objects.get(pk=response.json()["id"])
        self.assertIn(self.prompt_name, experiment.name)
        self.assertIn("v2", experiment.name)
        self.assertIn("v4", experiment.name)
        self.assertIn("latency", experiment.name)
        self.assertIn("cost", experiment.name)

    def test_400_when_versions_too_short(self) -> None:
        response = self._post(versions=[1])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("versions", response.json().get("attr", "") + str(response.json()))

    def test_400_when_versions_too_long(self) -> None:
        response = self._post(versions=list(range(1, 12)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_when_versions_have_duplicates(self) -> None:
        response = self._post(versions=[1, 1])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("duplicates", str(response.json()))

    def test_400_when_version_missing_for_prompt(self) -> None:
        response = self._post(versions=[1, 99])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("99", str(response.json()))

    def test_400_when_prompt_unknown(self) -> None:
        response = self._post(prompt_name="does-not-exist", versions=[1, 2])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("no llm analytics access", "llm_analytics", ["cost"], status.HTTP_403_FORBIDDEN),
            ("no evaluation access, eval pass rate", "evaluation", ["eval_pass_rate"], status.HTTP_403_FORBIDDEN),
            ("no evaluation access, cost only", "evaluation", ["cost"], status.HTTP_201_CREATED),
        ]
    )
    def test_resource_access(self, _name: str, denied_resource: str, templates: list[str], expected: int) -> None:
        features = self.organization.available_product_features or []
        features.append({"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL})
        self.organization.available_product_features = features
        self.organization.save()
        AccessControl.objects.create(team=self.team, resource=denied_resource, access_level="none")

        response = self._post(templates=templates)
        self.assertEqual(response.status_code, expected, response.content)

    @parameterized.expand(
        [
            ("without evaluation scope", ["experiment:write", "llm_prompt:read"], status.HTTP_403_FORBIDDEN),
            (
                "with evaluation scope",
                ["experiment:write", "llm_prompt:read", "evaluation:read"],
                status.HTTP_201_CREATED,
            ),
        ]
    )
    def test_eval_pass_rate_needs_evaluation_scope(self, _name: str, scopes: list[str], expected: int) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(user=self.user, label="prompt", secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/create_from_prompt/",
            {"prompt_name": self.prompt_name, "versions": [1, 2], "templates": ["eval_pass_rate"]},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, expected, response.content)

    def test_400_when_template_unknown(self) -> None:
        response = self._post(templates=["bogus"])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_when_templates_empty(self) -> None:
        response = self._post(templates=[])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_400_when_templates_have_duplicates(self) -> None:
        response = self._post(templates=["cost", "cost"])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("duplicates", str(response.json()))

    def test_list_filter_by_prompt_name(self) -> None:
        # Create two experiments for this prompt
        created1 = self._post(versions=[1, 2], templates=["cost"]).json()
        created2 = self._post(versions=[2, 3], templates=["latency"]).json()
        # And an unrelated experiment (no prompt_metadata)
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Unrelated experiment",
                "feature_flag_key": "unrelated-flag",
                "parameters": None,
            },
            format="json",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?prompt_name={self.prompt_name}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        returned_ids = {r["id"] for r in body["results"]}
        self.assertIn(created1["id"], returned_ids)
        self.assertIn(created2["id"], returned_ids)
        self.assertEqual(body["count"], 2)

    def test_list_filter_with_unknown_prompt_name_returns_empty(self) -> None:
        self._post(versions=[1, 2], templates=["cost"])
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?prompt_name=does-not-exist")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)
