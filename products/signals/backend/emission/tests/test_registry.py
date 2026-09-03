import pytest

from django.db.models import Field

from pydantic import ValidationError

from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import (
    _SIGNAL_TABLE_CONFIGS,
    SignalSourceTableConfig,
    get_signal_config,
    get_signal_source_identity,
    is_signal_emission_registered,
    register_signal_source,
)
from products.signals.backend.models import SignalSourceConfig
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

_BASE_FIELDS = {
    "source_product": "test_product",
    "source_type": "test",
    "emitter": lambda tid, r: None,
    "record_fetcher": data_warehouse_record_fetcher,
    "partition_field": "created_at",
    "fields": ("id",),
}


@pytest.fixture(autouse=True)
def _clean_registry():
    original = dict(_SIGNAL_TABLE_CONFIGS)
    yield
    _SIGNAL_TABLE_CONFIGS.clear()
    _SIGNAL_TABLE_CONFIGS.update(original)


class TestRegisterSignalSourceTable:
    def test_registers_and_retrieves_config(self):
        config = SignalSourceTableConfig(**_BASE_FIELDS)
        register_signal_source(ExternalDataSourceType.ZENDESK, "tickets", config)

        assert get_signal_config("Zendesk", "tickets") is config

    def test_overwrites_existing_registration(self):
        config_a = SignalSourceTableConfig(**_BASE_FIELDS)
        config_b = SignalSourceTableConfig(**{**_BASE_FIELDS, "partition_field": "updated_at"})
        register_signal_source(ExternalDataSourceType.ZENDESK, "tickets", config_a)
        register_signal_source(ExternalDataSourceType.ZENDESK, "tickets", config_b)

        assert get_signal_config("Zendesk", "tickets") is config_b


class TestGetSignalConfig:
    @pytest.mark.parametrize(
        "source_type,schema_name",
        [
            ("NonExistent", "tickets"),
            ("Zendesk", "nonexistent_table"),
            ("", ""),
            ("Zendesk", "acme/support.tickets"),
            ("Github", "posthog/posthog.pull_requests"),
        ],
    )
    def test_returns_none_for_unregistered(self, source_type, schema_name):
        assert get_signal_config(source_type, schema_name) is None


class TestQualifiedGithubSchemaNames:
    # The gate resolves through get_signal_source_identity and the activity through
    # get_signal_config, so normalizing only one of them leaves emission silently dead.
    @pytest.mark.parametrize(
        "lookup",
        [get_signal_config, is_signal_emission_registered, get_signal_source_identity],
        ids=["get_signal_config", "is_signal_emission_registered", "get_signal_source_identity"],
    )
    def test_every_lookup_resolves_qualified_name(self, lookup):
        assert lookup("Github", "posthog/posthog.issues")

    def test_qualified_name_resolves_to_the_bare_registration(self):
        assert get_signal_config("Github", "posthog/posthog.issues") is get_signal_config("Github", "issues")


class TestIsSignalEmissionRegistered:
    def test_true_when_registered(self):
        config = SignalSourceTableConfig(**{**_BASE_FIELDS, "partition_field": "time"})
        register_signal_source(ExternalDataSourceType.ZENDESK, "ticket_metric_events", config)

        assert is_signal_emission_registered("Zendesk", "ticket_metric_events") is True

    def test_false_when_not_registered(self):
        assert is_signal_emission_registered("Zendesk", "organizations") is False


class TestSignalSourceTableConfigValidation:
    @pytest.mark.parametrize(
        "field_name",
        ["actionability_prompt", "summarization_prompt"],
    )
    def test_rejects_prompt_without_description_placeholder(self, field_name):
        with pytest.raises(ValidationError, match="must contain.*description.*placeholder"):
            SignalSourceTableConfig(
                **{
                    **_BASE_FIELDS,
                    field_name: "No placeholder here",
                    **(
                        {"description_summarization_threshold_chars": 2000}
                        if field_name == "summarization_prompt"
                        else {}
                    ),
                }
            )

    @pytest.mark.parametrize(
        "field_name",
        ["actionability_prompt", "summarization_prompt"],
    )
    def test_accepts_prompt_with_description_placeholder(self, field_name):
        config = SignalSourceTableConfig(
            **{
                **_BASE_FIELDS,
                field_name: "Analyze: {description}",
                **({"description_summarization_threshold_chars": 2000} if field_name == "summarization_prompt" else {}),
            }
        )
        assert getattr(config, field_name) is not None

    def test_rejects_summarization_prompt_without_threshold(self):
        with pytest.raises(ValidationError, match="must both be set or both be None"):
            SignalSourceTableConfig(**{**_BASE_FIELDS, "summarization_prompt": "Summarize: {description}"})

    def test_rejects_threshold_without_summarization_prompt(self):
        with pytest.raises(ValidationError, match="must both be set or both be None"):
            SignalSourceTableConfig(**{**_BASE_FIELDS, "description_summarization_threshold_chars": 2000})

    @pytest.mark.parametrize("value", [0, -1, -100])
    def test_rejects_non_positive_threshold(self, value):
        with pytest.raises(ValidationError, match="greater than 0"):
            SignalSourceTableConfig(
                **{
                    **_BASE_FIELDS,
                    "summarization_prompt": "Summarize: {description}",
                    "description_summarization_threshold_chars": value,
                }
            )

    def test_accepts_both_summarization_fields_set(self):
        config = SignalSourceTableConfig(
            **{
                **_BASE_FIELDS,
                "summarization_prompt": "Summarize: {description}",
                "description_summarization_threshold_chars": 2000,
            }
        )
        assert config.summarization_prompt is not None
        assert config.description_summarization_threshold_chars == 2000

    def test_accepts_both_summarization_fields_none(self):
        config = SignalSourceTableConfig(**_BASE_FIELDS)
        assert config.summarization_prompt is None
        assert config.description_summarization_threshold_chars is None


# Captured at import, before the _clean_registry fixture can touch it.
_REGISTERED_IDENTITIES = sorted({(c.source_product, c.source_type) for c in _SIGNAL_TABLE_CONFIGS.values()})


def _field_choices(field_name: str) -> set[str]:
    # The field's own choices are what ModelSerializer turns into the ChoiceField the API validates.
    field = SignalSourceConfig._meta.get_field(field_name)
    assert isinstance(field, Field)
    return {value for value, _label in field.choices or ()}


class TestAutoRegistered:
    @pytest.mark.parametrize(
        "source_type,schema_name",
        [
            ("Zendesk", "tickets"),
            ("Github", "issues"),
            ("Linear", "issues"),
            ("Jira", "issues"),
            ("conversations", "tickets"),
        ],
    )
    def test_registered_on_module_load(self, source_type, schema_name):
        config = get_signal_config(source_type, schema_name)
        assert config is not None
        assert config.partition_field is not None
        assert config.record_fetcher is not None

    # Emission is gated on a SignalSourceConfig row, so an identity the config model doesn't accept
    # can never be enabled: the toggle posts it and the serializer rejects it with 400 invalid_choice.
    @pytest.mark.parametrize(
        "source_product,source_type",
        _REGISTERED_IDENTITIES,
        ids=[f"{product}-{source_type}" for product, source_type in _REGISTERED_IDENTITIES],
    )
    def test_registered_identity_is_an_enableable_config_choice(self, source_product: str, source_type: str) -> None:
        assert source_product in _field_choices("source_product")
        assert source_type in _field_choices("source_type")
