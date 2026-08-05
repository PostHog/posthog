"""Every field a service dataclass carries must survive its response serializer.

A DRF `Serializer` emits only the fields it declares. A key present in the input dict but absent
from the serializer is dropped silently — no error, no warning, no failing test. So a field added
to a service dataclass reaches HTTP and MCP consumers only if someone remembers to add it here
too, and forgetting looks exactly like the feature not existing.

That is not hypothetical. `UtmIssue.suggested_actions` — the only place `fix_platform_urls`,
`add_source_mapping` and `switch_to_id_match` are exposed at all — was declared on the dataclass
and populated by the audit, and never reached a single consumer because `UtmIssueSerializer` did
not list it. The service tests all passed: they assert on the dataclass, which was correct.

These tests compare the two field sets directly, so the next omission fails here instead of
shipping as a silently missing feature.
"""

from dataclasses import fields as dataclass_fields

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.marketing_analytics.backend.api import (
    CampaignAuditResultSerializer,
    CampaignMappingSuggestionSerializer,
    SourceMappingSuggestionSerializer,
    UtmAuditResponseSerializer,
    UtmEventSerializer,
    UtmIssueSerializer,
)
from products.marketing_analytics.backend.services.mapping_suggester import (
    CampaignMappingSuggestion,
    SourceMappingSuggestion,
)
from products.marketing_analytics.backend.services.types import (
    CampaignAuditResult,
    UtmAuditResponse,
    UtmEvent,
    UtmIssue,
)

# Deliberate omissions go here with a reason, so "not serialized" stays a decision rather than an
# oversight. Empty today: everything these dataclasses carry is meant to be public.
_INTENTIONALLY_UNSERIALIZED: dict[str, set[str]] = {}


class TestSerializerFieldParity(BaseTest):
    @parameterized.expand(
        [
            ("UtmIssue", UtmIssue, UtmIssueSerializer),
            ("CampaignAuditResult", CampaignAuditResult, CampaignAuditResultSerializer),
            ("UtmEvent", UtmEvent, UtmEventSerializer),
            ("UtmAuditResponse", UtmAuditResponse, UtmAuditResponseSerializer),
            ("SourceMappingSuggestion", SourceMappingSuggestion, SourceMappingSuggestionSerializer),
            ("CampaignMappingSuggestion", CampaignMappingSuggestion, CampaignMappingSuggestionSerializer),
        ]
    )
    def test_every_dataclass_field_is_serialized(self, name, dataclass_type, serializer_type):
        declared = set(serializer_type().get_fields())
        expected = {f.name for f in dataclass_fields(dataclass_type)} - _INTENTIONALLY_UNSERIALIZED.get(name, set())

        missing = expected - declared
        assert not missing, (
            f"{serializer_type.__name__} drops {sorted(missing)} from {name}. DRF discards undeclared "
            f"keys silently, so these never reach the API or MCP. Declare them, or add them to "
            f"_INTENTIONALLY_UNSERIALIZED with a reason."
        )

    @parameterized.expand(
        [
            ("UtmIssue", UtmIssue, UtmIssueSerializer),
            ("CampaignAuditResult", CampaignAuditResult, CampaignAuditResultSerializer),
            ("UtmEvent", UtmEvent, UtmEventSerializer),
            ("UtmAuditResponse", UtmAuditResponse, UtmAuditResponseSerializer),
            ("SourceMappingSuggestion", SourceMappingSuggestion, SourceMappingSuggestionSerializer),
            ("CampaignMappingSuggestion", CampaignMappingSuggestion, CampaignMappingSuggestionSerializer),
        ]
    )
    def test_serializer_declares_no_field_the_dataclass_lacks(self, name, dataclass_type, serializer_type):
        # The mirror image: a serializer field with no source is either a typo or a leftover from a
        # rename, and it surfaces as a required key the service can never supply.
        declared = set(serializer_type().get_fields())
        available = {f.name for f in dataclass_fields(dataclass_type)}

        extra = declared - available
        assert not extra, f"{serializer_type.__name__} declares {sorted(extra)}, which {name} does not carry."
