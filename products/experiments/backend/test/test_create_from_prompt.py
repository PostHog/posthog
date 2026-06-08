import json
from typing import Any

from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.ai_observability.backend.models.llm_prompt import LLMPrompt
from products.experiments.backend.llm_metric_templates import TEMPLATE_NAMES
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


class TestExperimentsCreateFromPrompt(APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        self.feature_flag_patcher = patch(
            "products.experiments.backend.presentation.views.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.addCleanup(self.feature_flag_patcher.stop)

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
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        keys = [t["key"] for t in body]
        assert set(keys) == set(TEMPLATE_NAMES)
        for entry in body:
            assert "label" in entry
            assert "description" in entry

    def test_create_from_prompt_404_when_feature_flag_disabled(self) -> None:
        self.mock_feature_enabled.return_value = False
        response = self._post()
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not Experiment.objects.filter(team_id=self.team.id).exists()

    def test_prompt_templates_404_when_feature_flag_disabled(self) -> None:
        self.mock_feature_enabled.return_value = False
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/prompt_templates/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [(name, n) for name in TEMPLATE_NAMES for n in (2, 3, 5)],
        name_func=lambda fn, _i, p: f"{fn.__name__}_{p.args[0]}_n{p.args[1]}",
    )
    def test_happy_path(self, template_name: str, n: int) -> None:
        versions = list(range(1, n + 1))
        response = self._post(templates=[template_name], versions=versions)

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()

        experiment = Experiment.objects.get(pk=body["id"])
        assert experiment.team_id == self.team.id
        assert experiment.is_draft
        assert experiment.parameters is not None
        assert experiment.metrics is not None

        # parameters.prompt_metadata round-trips
        prompt_metadata = experiment.parameters["prompt_metadata"]
        assert prompt_metadata["name"] == self.prompt_name
        assert prompt_metadata["templates"] == [template_name]
        assert prompt_metadata["versions"] == versions

        # Variant split distribution sums to 100 with the right shape
        variants = experiment.parameters["feature_flag_variants"]
        assert len(variants) == n
        assert sum(_split_distribution(variants)) == 100
        assert _split_distribution(variants) == _expected_splits(n)

        # Variant key naming: control + test (2-variant) or test-i (N>=3); names use v{version}
        assert variants[0]["key"] == "control"
        assert variants[0]["name"] == f"v{versions[0]}"
        for i, variant in enumerate(variants[1:], start=1):
            expected_key = "test" if n == 2 else f"test-{i}"
            assert variant["key"] == expected_key
            assert variant["name"] == f"v{versions[i]}"

        # Feature flag was created with the variants
        feature_flag = FeatureFlag.objects.get(key=experiment.feature_flag.key, team_id=self.team.id)
        flag_variants = feature_flag.filters["multivariate"]["variants"]
        assert [v["key"] for v in flag_variants] == [v["key"] for v in variants]

        # Each variant carries a JSON payload with {prompt_name, prompt_version} so the SDK can
        # read it via flags.get_flag_payload(...) without consulting any other state.
        payloads = feature_flag.filters["payloads"]
        assert set(payloads.keys()) == {v["key"] for v in variants}
        for variant, version in zip(variants, versions):
            decoded = json.loads(payloads[variant["key"]])
            assert decoded == {"prompt_name": self.prompt_name, "prompt_version": version}

        # Single primary metric, scoped to $ai_prompt_name = self.prompt_name
        assert len(experiment.metrics) == 1
        metric = experiment.metrics[0]
        assert metric["kind"] == "ExperimentMetric"
        source_or_numerator = metric.get("source") or metric.get("numerator")
        assert source_or_numerator is not None, f"metric had neither source nor numerator: {metric}"
        properties = source_or_numerator["properties"]
        prompt_filter = next(p for p in properties if p.get("key") == "$ai_prompt_name")
        assert prompt_filter["value"] == self.prompt_name

    def test_multiple_templates_creates_one_metric_each(self) -> None:
        # Pick all available templates so we exercise both mean and ratio shapes.
        templates = list(TEMPLATE_NAMES)
        response = self._post(templates=templates)
        assert response.status_code == status.HTTP_201_CREATED, response.content

        experiment = Experiment.objects.get(pk=response.json()["id"])
        assert experiment.parameters is not None
        assert experiment.metrics is not None
        assert experiment.parameters["prompt_metadata"]["templates"] == templates

        # One metric per template, in the same order, each scoped to the prompt.
        assert len(experiment.metrics) == len(templates)
        for metric in experiment.metrics:
            source_or_numerator = metric.get("source") or metric.get("numerator")
            assert source_or_numerator is not None
            prompt_filter = next(p for p in source_or_numerator["properties"] if p.get("key") == "$ai_prompt_name")
            assert prompt_filter["value"] == self.prompt_name

    def test_uses_provided_name_and_feature_flag_key(self) -> None:
        response = self._post(name="My custom name", feature_flag_key="my-custom-key")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        experiment = Experiment.objects.get(pk=response.json()["id"])
        assert experiment.name == "My custom name"
        assert experiment.feature_flag.key == "my-custom-key"

    def test_400_when_feature_flag_key_already_exists(self) -> None:
        # Pre-create a flag with the key the caller will try to claim. Reusing it would skip
        # the payload-writing path in ExperimentService and yield a broken experiment.
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="taken-key", name="Existing")

        response = self._post(feature_flag_key="taken-key")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "feature_flag_key" in str(response.json())
        assert not Experiment.objects.filter(team_id=self.team.id, feature_flag__key="taken-key").exists()

    def test_default_name_includes_versions_and_templates(self) -> None:
        response = self._post(versions=[2, 4], templates=["latency", "cost"])
        assert response.status_code == status.HTTP_201_CREATED, response.content
        experiment = Experiment.objects.get(pk=response.json()["id"])
        assert self.prompt_name in experiment.name
        assert "v2" in experiment.name
        assert "v4" in experiment.name
        assert "latency" in experiment.name
        assert "cost" in experiment.name

    def test_400_when_versions_too_short(self) -> None:
        response = self._post(versions=[1])
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "versions" in response.json().get("attr", "") + str(response.json())

    def test_400_when_versions_too_long(self) -> None:
        response = self._post(versions=list(range(1, 12)))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_when_versions_have_duplicates(self) -> None:
        response = self._post(versions=[1, 1])
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "duplicates" in str(response.json())

    def test_400_when_version_missing_for_prompt(self) -> None:
        response = self._post(versions=[1, 99])
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "99" in str(response.json())

    def test_400_when_prompt_unknown(self) -> None:
        response = self._post(prompt_name="does-not-exist", versions=[1, 2])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_when_template_unknown(self) -> None:
        response = self._post(templates=["bogus"])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_when_templates_empty(self) -> None:
        response = self._post(templates=[])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_400_when_templates_have_duplicates(self) -> None:
        response = self._post(templates=["cost", "cost"])
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "duplicates" in str(response.json())

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
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        returned_ids = {r["id"] for r in body["results"]}
        assert created1["id"] in returned_ids
        assert created2["id"] in returned_ids
        assert body["count"] == 2

    def test_list_filter_with_unknown_prompt_name_returns_empty(self) -> None:
        self._post(versions=[1, 2], templates=["cost"])
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?prompt_name=does-not-exist")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 0
