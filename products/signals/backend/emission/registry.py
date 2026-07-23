from __future__ import annotations

import enum
import dataclasses
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from products.warehouse_sources.backend.facade.sources import github_split_schema_name
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class InternalSourceType(str, enum.Enum):
    """Source types for internal PostHog products (not data warehouse imports)."""

    CONVERSATIONS = "conversations"


@dataclasses.dataclass(frozen=True)
class SignalEmitterOutput:
    source_product: str
    source_type: str
    source_id: str
    description: str
    weight: float
    extra: dict[str, Any]


# Type for signal emitter functions (None if the source has not enough meaningful data)
SignalEmitter = Callable[[int, dict[str, Any]], SignalEmitterOutput | None]

# Type for record fetcher functions: (team, config, runtime_context) -> records
# Each source defines its own fetcher (data warehouse uses HogQL, conversations uses Django ORM, etc.)
# Uses Any for Team to avoid forward-reference issues with Pydantic model resolution.
RecordFetcher = Callable[[Any, "SignalSourceTableConfig", dict[str, Any]], list[dict[str, Any]]]


class SignalSourceTableConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Must match SignalSourceConfig.SourceProduct and SignalSourceConfig.SourceType choices
    source_product: str
    source_type: str
    emitter: SignalEmitter
    # Each source defines how to fetch records — no default, must be explicit
    record_fetcher: RecordFetcher
    # Field used to filter records by time window (e.g. "created_at")
    partition_field: str
    # Columns to SELECT — only what the emitter and extra metadata need
    fields: tuple[str, ...]
    # Optional filter clause (interpreted by the fetcher — HogQL for data warehouse, ORM for Postgres sources)
    where_clause: str | None = None
    # Max records to process per sync
    max_records: int = 1000
    # Set to True when the source stores datetime values as strings (e.g. GitHub JSON fields)
    partition_field_is_datetime_string: bool = False
    # How far back to look for new records on the first sync
    first_sync_lookback_days: int = 7
    # LLM prompt to check if a record is actionable before emitting. If None, all records == actionable.
    actionability_prompt: str | None = None
    # LLM prompt to summarize descriptions that exceed the threshold. If None, no summarization is performed.
    summarization_prompt: str | None = None
    # How large the description can be before emitting
    description_summarization_threshold_chars: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_prompt_placeholders(self) -> SignalSourceTableConfig:
        for field_name in ("actionability_prompt", "summarization_prompt"):
            value = getattr(self, field_name)
            if value is not None and "{description}" not in value:
                raise ValueError(f"{field_name} must contain {{description}} placeholder")
        return self

    @model_validator(mode="after")
    def _validate_summarization_pair(self) -> SignalSourceTableConfig:
        has_prompt = self.summarization_prompt is not None
        has_threshold = self.description_summarization_threshold_chars is not None
        if has_prompt != has_threshold:
            raise ValueError(
                "summarization_prompt and description_summarization_threshold_chars must both be set or both be None"
            )
        return self


# Registry mapping (source_type, schema_name) -> config
_SIGNAL_TABLE_CONFIGS: dict[tuple[str, str], SignalSourceTableConfig] = {}


def register_signal_source(
    source_type: ExternalDataSourceType | InternalSourceType,
    schema_name: str,
    config: SignalSourceTableConfig,
) -> None:
    _SIGNAL_TABLE_CONFIGS[(source_type.value, schema_name)] = config


def _registry_key(source_type: str, schema_name: str) -> tuple[str, str]:
    """GitHub alone qualifies its schema rows (`owner/repo.issues`); emitters register the bare endpoint."""
    if source_type == ExternalDataSourceType.GITHUB.value:
        _, endpoint = github_split_schema_name(schema_name)
        return (source_type, endpoint)
    return (source_type, schema_name)


def get_signal_config(source_type: str, schema_name: str) -> SignalSourceTableConfig | None:
    return _SIGNAL_TABLE_CONFIGS.get(_registry_key(source_type, schema_name))


def is_signal_emission_registered(source_type: str, schema_name: str) -> bool:
    return _registry_key(source_type, schema_name) in _SIGNAL_TABLE_CONFIGS


def get_signal_source_identity(source_type: str, schema_name: str) -> tuple[str, str] | None:
    config = get_signal_config(source_type, schema_name)
    return (config.source_product, config.source_type) if config else None


def _register_all_emitters() -> None:
    # Tier-3 feedback / reviews
    from products.signals.backend.emission.aha_ideas import AHA_CONFIG
    from products.signals.backend.emission.appfigures_reviews import APPFIGURES_CONFIG
    from products.signals.backend.emission.appfollow_reviews import APPFOLLOW_CONFIG
    from products.signals.backend.emission.asknicely_responses import ASKNICELY_CONFIG
    from products.signals.backend.emission.bugsnag_errors import BUGSNAG_CONFIG
    from products.signals.backend.emission.canny_posts import CANNY_CONFIG
    from products.signals.backend.emission.conversations_tickets import CONVERSATIONS_TICKETS_CONFIG
    from products.signals.backend.emission.dixa_conversations import DIXA_CONFIG
    from products.signals.backend.emission.featurebase_posts import FEATUREBASE_CONFIG
    from products.signals.backend.emission.freshdesk_tickets import FRESHDESK_CONFIG
    from products.signals.backend.emission.freshservice_tickets import FRESHSERVICE_CONFIG
    from products.signals.backend.emission.frill_ideas import FRILL_CONFIG
    from products.signals.backend.emission.front_conversations import FRONT_CONFIG
    from products.signals.backend.emission.gitea_issues import GITEA_CONFIG
    from products.signals.backend.emission.github_issues import GITHUB_ISSUES_CONFIG
    from products.signals.backend.emission.gitlab_issues import GITLAB_CONFIG
    from products.signals.backend.emission.gorgias_tickets import GORGIAS_CONFIG
    from products.signals.backend.emission.honeybadger_faults import HONEYBADGER_CONFIG
    from products.signals.backend.emission.hubspot_tickets import HUBSPOT_CONFIG
    from products.signals.backend.emission.intercom_conversations import INTERCOM_CONFIG
    from products.signals.backend.emission.jira_issues import JIRA_ISSUES_CONFIG
    from products.signals.backend.emission.judgeme_reviews_reviews import JUDGEME_REVIEWS_CONFIG
    from products.signals.backend.emission.kustomer_conversations import KUSTOMER_CONFIG
    from products.signals.backend.emission.linear_issues import LINEAR_ISSUES_CONFIG
    from products.signals.backend.emission.pganalyze_issues import PGANALYZE_ISSUES_CONFIG
    from products.signals.backend.emission.plain_threads import PLAIN_CONFIG
    from products.signals.backend.emission.productboard_notes import PRODUCTBOARD_CONFIG

    # Tier-2 security scanners
    from products.signals.backend.emission.rapid7_insightvm_vulnerabilities import RAPID7_INSIGHTVM_CONFIG
    from products.signals.backend.emission.raygun_error_groups import RAYGUN_CONFIG
    from products.signals.backend.emission.retently_feedback import RETENTLY_CONFIG
    from products.signals.backend.emission.rollbar_items import ROLLBAR_CONFIG
    from products.signals.backend.emission.semgrep_sast_findings import SEMGREP_CONFIG
    from products.signals.backend.emission.sentry_issues import SENTRY_CONFIG
    from products.signals.backend.emission.shortcut_stories import SHORTCUT_CONFIG
    from products.signals.backend.emission.snyk_issues import SNYK_CONFIG
    from products.signals.backend.emission.sonarqube_issues import SONARQUBE_CONFIG
    from products.signals.backend.emission.uservoice_suggestions import USERVOICE_CONFIG
    from products.signals.backend.emission.zendesk_tickets import ZENDESK_TICKETS_CONFIG

    register_signal_source(ExternalDataSourceType.ZENDESK, "tickets", ZENDESK_TICKETS_CONFIG)
    register_signal_source(ExternalDataSourceType.GITHUB, "issues", GITHUB_ISSUES_CONFIG)
    register_signal_source(ExternalDataSourceType.LINEAR, "issues", LINEAR_ISSUES_CONFIG)
    register_signal_source(ExternalDataSourceType.JIRA, "issues", JIRA_ISSUES_CONFIG)
    register_signal_source(ExternalDataSourceType.PGANALYZE, "issues", PGANALYZE_ISSUES_CONFIG)
    register_signal_source(InternalSourceType.CONVERSATIONS, "tickets", CONVERSATIONS_TICKETS_CONFIG)
    # Tier-1 support / helpdesk (record kind: ticket)
    register_signal_source(ExternalDataSourceType.FRESHDESK, "tickets", FRESHDESK_CONFIG)
    register_signal_source(ExternalDataSourceType.FRESHSERVICE, "tickets", FRESHSERVICE_CONFIG)
    register_signal_source(ExternalDataSourceType.FRONT, "conversations", FRONT_CONFIG)
    register_signal_source(ExternalDataSourceType.GORGIAS, "tickets", GORGIAS_CONFIG)
    register_signal_source(ExternalDataSourceType.KUSTOMER, "conversations", KUSTOMER_CONFIG)
    register_signal_source(ExternalDataSourceType.DIXA, "conversations", DIXA_CONFIG)
    register_signal_source(ExternalDataSourceType.PLAIN, "threads", PLAIN_CONFIG)
    # Tier-1 issue trackers (record kind: issue)
    register_signal_source(ExternalDataSourceType.GITLAB, "issues", GITLAB_CONFIG)
    register_signal_source(ExternalDataSourceType.GITEA, "issues", GITEA_CONFIG)
    register_signal_source(ExternalDataSourceType.SHORTCUT, "stories", SHORTCUT_CONFIG)
    # Tier-1 error tracking (record kind: issue)
    register_signal_source(ExternalDataSourceType.SENTRY, "issues", SENTRY_CONFIG)
    register_signal_source(ExternalDataSourceType.ROLLBAR, "items", ROLLBAR_CONFIG)
    register_signal_source(ExternalDataSourceType.BUGSNAG, "errors", BUGSNAG_CONFIG)
    register_signal_source(ExternalDataSourceType.HONEYBADGER, "faults", HONEYBADGER_CONFIG)
    register_signal_source(ExternalDataSourceType.RAYGUN, "error_groups", RAYGUN_CONFIG)
    # Tier-2 security scanners (record kind: scanner_finding)
    register_signal_source(ExternalDataSourceType.SNYK, "issues", SNYK_CONFIG)
    register_signal_source(ExternalDataSourceType.SONARQUBE, "issues", SONARQUBE_CONFIG)
    register_signal_source(ExternalDataSourceType.SEMGREP, "sast_findings", SEMGREP_CONFIG)
    register_signal_source(ExternalDataSourceType.RAPID7INSIGHTVM, "vulnerabilities", RAPID7_INSIGHTVM_CONFIG)
    # Tier-3 product feedback / feature requests (record kind: feedback)
    register_signal_source(ExternalDataSourceType.FEATUREBASE, "posts", FEATUREBASE_CONFIG)
    register_signal_source(ExternalDataSourceType.FRILL, "ideas", FRILL_CONFIG)
    register_signal_source(ExternalDataSourceType.AHA, "ideas", AHA_CONFIG)
    register_signal_source(ExternalDataSourceType.USERVOICE, "suggestions", USERVOICE_CONFIG)
    register_signal_source(ExternalDataSourceType.PRODUCTBOARD, "notes", PRODUCTBOARD_CONFIG)
    register_signal_source(ExternalDataSourceType.CANNY, "posts", CANNY_CONFIG)
    register_signal_source(ExternalDataSourceType.ASKNICELY, "responses", ASKNICELY_CONFIG)
    register_signal_source(ExternalDataSourceType.RETENTLY, "feedback", RETENTLY_CONFIG)
    # Tier-3 reviews (record kind: review)
    register_signal_source(ExternalDataSourceType.APPFIGURES, "reviews", APPFIGURES_CONFIG)
    register_signal_source(ExternalDataSourceType.APPFOLLOW, "reviews", APPFOLLOW_CONFIG)
    register_signal_source(ExternalDataSourceType.JUDGEMEREVIEWS, "reviews", JUDGEME_REVIEWS_CONFIG)
    # OAuth-connected support sources (record kind: ticket)
    register_signal_source(ExternalDataSourceType.INTERCOM, "conversations", INTERCOM_CONFIG)
    register_signal_source(ExternalDataSourceType.HUBSPOT, "tickets", HUBSPOT_CONFIG)


_register_all_emitters()
