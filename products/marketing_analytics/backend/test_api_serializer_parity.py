"""Every field a service dataclass carries must survive its response serializer.

A DRF `Serializer` drops an undeclared key silently — no error, no failing test, so a forgotten
field looks exactly like the feature not existing. `UtmIssue.suggested_actions` reached no consumer
for that reason while every service test passed, because they assert on the dataclass.
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

# Deliberate omissions go here with a reason, so "not serialized" stays a decision.
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
        # A serializer field with no source is a required key the service can never supply.
        declared = set(serializer_type().get_fields())
        available = {f.name for f in dataclass_fields(dataclass_type)}

        extra = declared - available
        assert not extra, f"{serializer_type.__name__} declares {sorted(extra)}, which {name} does not carry."
