import pytest
from unittest.mock import MagicMock, patch

from django.db.models import Field

from pydantic import ValidationError

from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_aggregation, find_hogql_function, find_hogql_posthog_function
from posthog.hogql.visitor import TraversingVisitor

from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.google_search_console_opportunities import google_search_console_record_fetcher
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


_HOGQL_RECORD_FETCHERS = (data_warehouse_record_fetcher, google_search_console_record_fetcher)


class _CallNameCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.names: list[str] = []

    def visit_call(self, node: ast.Call) -> None:
        self.names.append(node.name)
        super().visit_call(node)


def _build_fetcher_query(config: SignalSourceTableConfig, last_synced_at: str | None) -> ast.SelectQuery:
    """Run the real fetcher against a stubbed executor and return the AST it built."""
    captured: dict[str, ast.SelectQuery] = {}

    def fake_execute(query, **kwargs):
        captured["query"] = query
        result = MagicMock()
        result.results = []
        result.columns = []
        return result

    with patch(
        "products.signals.backend.emission.fetchers.data_warehouse.execute_hogql_query", side_effect=fake_execute
    ):
        data_warehouse_record_fetcher(
            team=MagicMock(),
            config=config,
            context={"table_name": "source.table", "last_synced_at": last_synced_at, "extra": {}},
        )
    return captured["query"]


def _unknown_function_names(query: ast.SelectQuery) -> list[str]:
    collector = _CallNameCollector()
    collector.visit(query)
    return [
        name
        for name in collector.names
        if not (find_hogql_function(name) or find_hogql_aggregation(name) or find_hogql_posthog_function(name))
    ]


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


class TestRegisteredConfigsBuildValidHogQL:
    """Guard the whole registry: a source whose query cannot parse or names an unknown function
    fails here instead of failing silently on every sync in production."""

    @staticmethod
    def _hogql_configs() -> list[tuple[tuple[str, str], SignalSourceTableConfig]]:
        return [
            (key, config)
            for key, config in sorted(_SIGNAL_TABLE_CONFIGS.items())
            if config.record_fetcher in _HOGQL_RECORD_FETCHERS
        ]

    @pytest.mark.parametrize("last_synced_at", [None, "2025-01-01T00:00:00Z"])
    def test_every_source_query_parses_and_uses_known_functions(self, last_synced_at):
        configs = self._hogql_configs()
        assert len(configs) > 1, "the registry sweep matched no warehouse-backed source"
        unknown = {
            key: _unknown_function_names(_build_fetcher_query(config, last_synced_at)) for key, config in configs
        }
        assert {key: names for key, names in unknown.items() if names} == {}
