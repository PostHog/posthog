from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management.base import CommandError

from posthog.models.organization import Organization

from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch
from products.growth.dags import ai_enrichment
from products.growth.dags.ai_enrichment import ai_enrichment_job, count_pending_candidates, is_ai_enrichment_registered

_MODULE = "products.growth.dags.ai_enrichment"

_OUTPUT_FIELDS = [{"key": "is_ai", "type": "boolean", "description": ""}]


class _EnrichmentDagTestCase(BaseTest):
    def _config(self, **overrides: Any) -> EnrichmentPromptConfig:
        params: dict[str, Any] = {
            "name": "test_label",
            "version": "v1",
            "prompt_text": "... Email: {email}",
            "model": "gpt-5-mini",
            "input_fields": ["name"],
            "output_fields": _OUTPUT_FIELDS,
            "is_active": True,
        }
        params.update(overrides)
        return EnrichmentPromptConfig.objects.create(**params)

    def _fetch(self, organization: Organization | None = None) -> OrganizationEnrichmentFetch:
        return OrganizationEnrichmentFetch.objects.create(
            organization=organization or self.organization, provider="harmonic", payload={"name": "Acme"}
        )


class TestCountPendingCandidates(_EnrichmentDagTestCase):
    def test_counts_a_fetch_with_no_verdict_yet(self):
        self._config()
        self._fetch()

        assert count_pending_candidates("test_label", "v1") == 1

    def test_excludes_a_fetch_already_labeled_under_this_exact_version(self):
        config = self._config()
        fetch = self._fetch()
        EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name="test_label",
            prompt_version=config.version,
            prompt_hash="h",
            model="gpt-5-mini",
        )

        assert count_pending_candidates("test_label", config.version) == 0

    def test_a_verdict_under_a_retired_version_does_not_hide_the_candidate(self):
        # A rename or re-version leaves prior verdicts stamped with the old version - see
        # EnrichmentPromptConfig's docstring. The pending count must key off the exact
        # (label, active version) pair the caller is about to run, not just the label.
        fetch = self._fetch()
        EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name="test_label",
            prompt_version="v0-retired",
            prompt_hash="h",
            model="gpt-5-mini",
        )

        assert count_pending_candidates("test_label", "v1") == 1

    def test_excludes_an_org_that_declined_ai_processing(self):
        self._config()
        self._fetch()
        Organization.objects.filter(id=self.organization.id).update(is_ai_data_processing_approved=False)

        assert count_pending_candidates("test_label", "v1") == 0

    def test_zero_when_there_is_nothing_pending(self):
        assert count_pending_candidates("test_label", "v1") == 0


class TestAiEnrichmentJob(_EnrichmentDagTestCase):
    def test_calls_batch_command_once_per_active_label_with_the_configured_limit_and_workers(self):
        self._config(name="label_a")
        self._config(name="label_b")
        # No pending fetches for either label, so the absence-of-output check can't fire and
        # mask what this test is actually asserting.

        with patch(f"{_MODULE}.call_command") as mock_call_command:
            result = ai_enrichment_job.execute_in_process(
                run_config={"ops": {"classify_pending_organizations_op": {"config": {"limit": 42, "workers": 3}}}}
            )

        assert result.success
        calls_by_label = {call.kwargs["label"]: call for call in mock_call_command.call_args_list}
        assert calls_by_label.keys() == {"label_a", "label_b"}
        for call in calls_by_label.values():
            assert call.args == ("enrichment_label_batch",)
            assert call.kwargs["limit"] == 42
            assert call.kwargs["workers"] == 3

    def test_default_limit_matches_the_module_constant(self):
        self._config()

        with patch(f"{_MODULE}.call_command") as mock_call_command:
            result = ai_enrichment_job.execute_in_process()

        assert result.success
        assert mock_call_command.call_args.kwargs["limit"] == ai_enrichment.DEFAULT_LABEL_LIMIT

    def test_only_active_configs_are_classified(self):
        self._config(name="inactive_label", is_active=False)

        with patch(f"{_MODULE}.call_command") as mock_call_command:
            result = ai_enrichment_job.execute_in_process()

        assert result.success
        mock_call_command.assert_not_called()

    def test_no_active_labels_is_a_no_op_success(self):
        with patch(f"{_MODULE}.call_command") as mock_call_command:
            result = ai_enrichment_job.execute_in_process()

        assert result.success
        mock_call_command.assert_not_called()

    def test_raises_when_candidates_exist_but_the_command_creates_no_verdicts(self):
        # A run that finds pending orgs but persists nothing is exactly the silent-failure shape
        # this check exists to catch - the command's own exit code alone can't distinguish it
        # from a legitimately quiet day.
        self._config()
        self._fetch()

        with patch(f"{_MODULE}.call_command"), pytest.raises(Exception, match="candidates but 0 verdicts created"):
            ai_enrichment_job.execute_in_process()

    def test_does_not_raise_when_there_were_no_candidates_to_begin_with(self):
        self._config()

        with patch(f"{_MODULE}.call_command") as mock_call_command:
            result = ai_enrichment_job.execute_in_process()

        assert result.success
        mock_call_command.assert_called_once()

    def test_a_command_error_fails_the_job_and_is_captured(self):
        self._config()
        self._fetch()

        with (
            patch(f"{_MODULE}.call_command", side_effect=CommandError("aborted after 25 consecutive failures")),
            patch(f"{_MODULE}.capture_exception") as capture_mock,
            pytest.raises(Exception, match="command failed"),
        ):
            ai_enrichment_job.execute_in_process()

        capture_mock.assert_called_once()

    def test_succeeds_when_the_command_actually_creates_a_verdict(self):
        config = self._config()
        fetch = self._fetch()

        def _fake_batch_run(_name: str, **kwargs: Any) -> None:
            EnrichmentLabelResult.objects.create(
                organization=fetch.organization,
                fetch=fetch,
                label_name=config.name,
                prompt_version=config.version,
                prompt_hash="h",
                model="gpt-5-mini",
            )

        with patch(f"{_MODULE}.call_command", side_effect=_fake_batch_run):
            result = ai_enrichment_job.execute_in_process()

        assert result.success
        assert EnrichmentLabelResult.objects.count() == 1

    def test_one_labels_absence_failure_does_not_stop_another_label_from_running(self):
        self._config(name="silent_label")
        self._fetch()
        other_config = self._config(name="working_label")
        other_org = Organization.objects.create(name="other")
        other_fetch = self._fetch(organization=other_org)

        def _fake_batch_run(_name: str, **kwargs: Any) -> None:
            if kwargs["label"] == "working_label":
                EnrichmentLabelResult.objects.create(
                    organization=other_org,
                    fetch=other_fetch,
                    label_name=other_config.name,
                    prompt_version=other_config.version,
                    prompt_hash="h",
                    model="gpt-5-mini",
                )
            # silent_label's call does nothing, simulating the silent-failure shape.

        with (
            patch(f"{_MODULE}.call_command", side_effect=_fake_batch_run),
            pytest.raises(Exception, match="silent_label"),
        ):
            ai_enrichment_job.execute_in_process()

        # working_label still ran to completion despite silent_label's problem.
        assert EnrichmentLabelResult.objects.filter(label_name="working_label").count() == 1


@pytest.mark.parametrize(
    "cloud_deployment,registered",
    [(None, True), ("LOCAL", True), ("DEV", True), ("US", True), ("EU", False)],
)
def test_ai_enrichment_registered_per_environment(cloud_deployment: str | None, registered: bool) -> None:
    with patch.object(ai_enrichment.settings, "CLOUD_DEPLOYMENT", cloud_deployment):
        assert is_ai_enrichment_registered() is registered
