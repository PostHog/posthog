from typing import Any

from posthog.test.base import BaseTest

from django.contrib.admin import AdminSite
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from products.growth.backend.admin import (
    EnrichmentLabelNameFilter,
    EnrichmentLabelResultAdmin,
    EnrichmentPromptConfigAdmin,
    EnrichmentPromptConfigForm,
    EnrichmentPromptVersionFilter,
)
from products.growth.backend.enrichment.labels import MAX_INPUT_COLUMNS
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

_VALID_OUTPUT_FIELDS = [
    {"key": "ai_pilled", "type": "boolean", "description": ""},
    {"key": "confidence", "type": "number", "description": ""},
]


class TestEnrichmentPromptConfigFormCleanInputFields(SimpleTestCase):
    @parameterized.expand(
        [
            ("not_a_list", "name"),
            ("contains_non_string", ["name", 5]),
            ("contains_empty_string", ["name", ""]),
            ("more_than_reach_the_prompt", [f"field_{i}" for i in range(MAX_INPUT_COLUMNS + 1)]),
        ]
    )
    def test_rejects_malformed_input_fields(self, _name: str, bad_value: Any) -> None:
        form = EnrichmentPromptConfigForm()
        form.cleaned_data = {"input_fields": bad_value}

        with self.assertRaises(ValidationError):
            form.clean_input_fields()

    def test_accepts_a_list_of_non_empty_strings(self) -> None:
        form = EnrichmentPromptConfigForm()
        form.cleaned_data = {"input_fields": ["name", "funding.fundingStage"]}

        assert form.clean_input_fields() == ["name", "funding.fundingStage"]


class TestEnrichmentPromptConfigFormCleanOutputFields(SimpleTestCase):
    @parameterized.expand(
        [
            ("not_a_list", "ai_pilled"),
            ("entry_not_a_dict", ["ai_pilled"]),
            ("missing_key", [{"type": "boolean"}]),
            ("missing_type", [{"key": "ai_pilled"}]),
            ("unknown_type", [{"key": "ai_pilled", "type": "object"}]),
            ("reserved_key_meta", [{"key": "meta", "type": "string"}]),
            ("reserved_key_inputs", [{"key": "inputs", "type": "string"}]),
            ("only_min", [{"key": "score", "type": "number", "min": 0}]),
            ("range_on_a_string", [{"key": "score", "type": "string", "min": 0, "max": 1}]),
            ("min_above_max", [{"key": "score", "type": "number", "min": 10, "max": 1}]),
        ]
    )
    def test_rejects_malformed_output_fields(self, _name: str, bad_value: Any) -> None:
        form = EnrichmentPromptConfigForm()
        form.cleaned_data = {"output_fields": bad_value}

        with self.assertRaises(ValidationError):
            form.clean_output_fields()

    def test_accepts_well_formed_output_fields(self) -> None:
        form = EnrichmentPromptConfigForm()
        form.cleaned_data = {"output_fields": _VALID_OUTPUT_FIELDS}

        assert form.clean_output_fields() == _VALID_OUTPUT_FIELDS

    def test_accepts_an_explicit_numeric_range(self) -> None:
        ranged = [{"key": "score", "type": "number", "min": 0, "max": 100}]
        form = EnrichmentPromptConfigForm()
        form.cleaned_data = {"output_fields": ranged}

        assert form.clean_output_fields() == ranged


class _GrowthAdminTestCase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Migration 0006 seeds an ai_pilled config, and these tests assert over the whole table.
        EnrichmentPromptConfig.objects.all().delete()

    def _config(self, **overrides: Any) -> EnrichmentPromptConfig:
        params: dict[str, Any] = {
            "name": "ai_pilled",
            "version": "v1",
            "prompt_text": "classify {email}",
            "model": "gpt-5-mini",
            "input_fields": ["name"],
            "output_fields": _VALID_OUTPUT_FIELDS,
        }
        params.update(overrides)
        return EnrichmentPromptConfig.objects.create(**params)

    def _fetch(self) -> OrganizationEnrichmentFetch:
        return OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )

    def _result(self, config: EnrichmentPromptConfig, fetch: OrganizationEnrichmentFetch) -> EnrichmentLabelResult:
        return EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name=config.name,
            prompt_version=config.version,
            prompt_hash=config.content_hash,
            model=config.model,
            output={"ai_pilled": True},
            inputs={"signup_domain": "acme.com"},
        )


class TestEnrichmentPromptConfigAdminReadonlyFields(_GrowthAdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = EnrichmentPromptConfigAdmin(EnrichmentPromptConfig, AdminSite())
        self.request = RequestFactory().get("/admin/growth/enrichmentpromptconfig/")

    def test_behavior_fields_stay_editable_with_no_results(self) -> None:
        config = self._config()

        readonly = self.admin.get_readonly_fields(self.request, config)

        assert "prompt_text" not in readonly
        assert "output_fields" not in readonly

    def test_behavior_fields_lock_once_results_exist_for_this_version(self) -> None:
        config = self._config()
        self._result(config, self._fetch())

        readonly = self.admin.get_readonly_fields(self.request, config)

        for field in ("name", "version", "prompt_text", "model", "input_fields", "output_fields"):
            assert field in readonly

    def test_a_sibling_version_with_results_does_not_lock_a_fresh_version(self) -> None:
        scored_config = self._config(version="v1")
        fresh_config = self._config(version="v2")
        self._result(scored_config, self._fetch())

        readonly = self.admin.get_readonly_fields(self.request, fresh_config)

        assert "prompt_text" not in readonly


class TestEnrichmentPromptConfigAdminSaveModel(_GrowthAdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = EnrichmentPromptConfigAdmin(EnrichmentPromptConfig, AdminSite())

    def _request(self) -> Any:
        request = RequestFactory().post("/admin/growth/enrichmentpromptconfig/add/")
        request.user = self.user
        return request

    def test_created_by_is_stamped_from_the_request_user_on_add(self) -> None:
        obj = EnrichmentPromptConfig(
            name="ai_pilled",
            version="v1",
            prompt_text="classify {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=_VALID_OUTPUT_FIELDS,
        )

        self.admin.save_model(self._request(), obj, form=EnrichmentPromptConfigForm(), change=False)

        assert obj.created_by_id == self.user.id

    def test_created_by_is_not_overwritten_on_change(self) -> None:
        other_user = self._create_user("other-config-owner@example.com")
        obj = self._config(created_by=other_user)

        self.admin.save_model(self._request(), obj, form=EnrichmentPromptConfigForm(), change=True)

        assert obj.created_by_id == other_user.id


class TestEnrichmentLabelResultAdminSearch(_GrowthAdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = EnrichmentLabelResultAdmin(EnrichmentLabelResult, AdminSite())

    def test_search_by_exact_organization_id_finds_the_row(self) -> None:
        result = self._result(self._config(), self._fetch())
        request = RequestFactory().get("/admin/growth/enrichmentlabelresult/")

        queryset, _ = self.admin.get_search_results(
            request, EnrichmentLabelResult.objects.all(), str(self.organization.id)
        )

        assert list(queryset) == [result]

    def test_search_with_a_non_matching_term_returns_empty_without_erroring(self) -> None:
        # organization_id is a UUID column: comparing it against a search term that isn't itself
        # a UUID (e.g. via a plain icontains) raises "operator does not exist: uuid ~~* unknown"
        # in Postgres, rather than just matching nothing. This proves the search survives that.
        self._result(self._config(), self._fetch())
        request = RequestFactory().get("/admin/growth/enrichmentlabelresult/")

        queryset, _ = self.admin.get_search_results(request, EnrichmentLabelResult.objects.all(), "not-a-uuid")

        assert list(queryset) == []


class TestEnrichmentLabelResultAdminFilters(_GrowthAdminTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = EnrichmentLabelResultAdmin(EnrichmentLabelResult, AdminSite())

    def test_label_name_choices_come_from_prompt_configs_not_results(self) -> None:
        # No EnrichmentLabelResult rows exist at all: a filter sourced from a SELECT DISTINCT
        # over that table would offer no choices even though a label is configured.
        self._config(name="ai_pilled")
        request = RequestFactory().get("/admin/growth/enrichmentlabelresult/")

        choices = EnrichmentLabelNameFilter(request, {}, EnrichmentLabelResult, self.admin).lookup_choices

        assert choices == [("ai_pilled", "ai_pilled")]

    def test_prompt_version_choices_come_from_prompt_configs(self) -> None:
        self._config(version="ai-pilled-clay-v1")
        request = RequestFactory().get("/admin/growth/enrichmentlabelresult/")

        choices = EnrichmentPromptVersionFilter(request, {}, EnrichmentLabelResult, self.admin).lookup_choices

        assert choices == [("ai-pilled-clay-v1", "ai-pilled-clay-v1")]

    def test_label_name_filter_narrows_the_queryset(self) -> None:
        fetch = self._fetch()
        matching = self._result(self._config(name="ai_pilled"), fetch)
        self._result(self._config(name="other_label", version="v1-other"), fetch)
        request = RequestFactory().get("/admin/growth/enrichmentlabelresult/", {"label_name": "ai_pilled"})

        queryset = EnrichmentLabelNameFilter(request, request.GET.copy(), EnrichmentLabelResult, self.admin).queryset(
            request, EnrichmentLabelResult.objects.all()
        )

        assert list(queryset) == [matching]


class TestFetchDeletionPreservesLabelResults(_GrowthAdminTestCase):
    def test_deleting_a_fetch_nulls_the_result_instead_of_cascading(self) -> None:
        fetch = self._fetch()
        result = self._result(self._config(), fetch)

        fetch.delete()
        result.refresh_from_db()

        assert result.fetch_id is None
        assert result.output == {"ai_pilled": True}
