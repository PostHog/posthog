"""Read the ICP fit score's wizard input for one organization.

The read is strict about failure: an unreachable group store or scan store raises, because
scoring an org on inputs we failed to fetch would write a silently-too-low score. Callers
degrade to writing firmographics without a score on a raise, and get another chance at the
delayed recheck.

The wizard input is true when a stored codebase scan of any of the org's projects finds one of
this module's LLM tool kinds, or when the organization group still carries the stamp older wizards set.
"""

import dataclasses

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.models.group.util import get_group_by_key
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.team import Team
from posthog.utils import get_instance_region

from products.growth.backend.enrichment.writer import ORGANIZATION_GROUP_TYPE
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.wizard.backend.facade import api as wizard_facade

# Set by wizards before they reported scans to PostHog. Still read, so those orgs keep the input.
WIZARD_AI_SDK_DETECTED_PROPERTY = "wizard_ai_sdk_detected"
# Tool kinds from the wizard's scan that mean the org builds with LLMs. This list is the scoring
# decision, so it lives here rather than in the wizard's tool catalog.
LLM_TOOL_KINDS: frozenset[ExternalDataSourceType] = frozenset(
    {
        ExternalDataSourceType.ANTHROPIC,
        ExternalDataSourceType.ASSEMBLYAI,
        ExternalDataSourceType.BROWSERBASE,
        ExternalDataSourceType.COHERE,
        ExternalDataSourceType.DEEPGRAM,
        ExternalDataSourceType.E2B,
        ExternalDataSourceType.ELEVENLABS,
        ExternalDataSourceType.FIRECRAWL,
        ExternalDataSourceType.FIREWORKSAI,
        ExternalDataSourceType.GROQ,
        ExternalDataSourceType.HELICONE,
        ExternalDataSourceType.HUGGINGFACE,
        ExternalDataSourceType.LANGSMITH,
        ExternalDataSourceType.LANGFUSE,
        ExternalDataSourceType.LLAMACLOUD,
        ExternalDataSourceType.MEM0,
        ExternalDataSourceType.MISTRALAI,
        ExternalDataSourceType.OPENAI,
        ExternalDataSourceType.OPENROUTER,
        ExternalDataSourceType.REPLICATE,
        ExternalDataSourceType.TOGETHERAI,
        ExternalDataSourceType.VELLUM,
        ExternalDataSourceType.WEIGHTSANDBIASES,
        ExternalDataSourceType.ZEP,
    }
)


class OrganizationGroupTypeMissing(Exception):
    """The internal project has no `organization` group type — a config problem, not a null input."""


@frozen
class WizardBridgeInputs:
    """Whether the wizard found an LLM SDK in one org's code. False when it never scanned."""

    ai_sdk_detected: bool = False


@frozen
class OrganizationBridgeInputs:
    wizard: WizardBridgeInputs = dataclasses.field(default_factory=WizardBridgeInputs)


def _organization_group_type_index(team: Team) -> int:
    for group_type in get_group_types_for_project(team.project_id):
        if group_type["group_type"] == ORGANIZATION_GROUP_TYPE:
            return int(group_type["group_type_index"])
    # get_group_types_for_project swallows lookup failures into an empty list, so "not found"
    # here can equally mean the mapping store was unreachable. Either way it is not a null input.
    raise OrganizationGroupTypeMissing(f"no `{ORGANIZATION_GROUP_TYPE}` group type on project {team.project_id}")


def read_organization_bridge_inputs(*, organization_id: str) -> OrganizationBridgeInputs:
    """Fetch score inputs for one org. Raises when the group store or the wizard's scan store cannot be read."""
    # The organization group lives only in the US internal project, so outside US there is
    # nothing to read.
    if get_instance_region() != "US":
        return OrganizationBridgeInputs()
    # The internal project the enrichment group properties are projected onto, and the same one
    # the ProductLed_Outbound consumer reads them back from (ee/billing/dags/productled_outbound_targets.py).
    team = Team.objects.get(id=settings.GROWTH_ENRICHMENT_INTERNAL_TEAM_ID)
    group = get_group_by_key(
        team_id=team.id,
        group_type_index=_organization_group_type_index(team),
        group_key=organization_id,
    )
    properties = (group.group_properties or {}) if group is not None else {}
    wizard = WizardBridgeInputs(
        ai_sdk_detected=properties.get(WIZARD_AI_SDK_DETECTED_PROPERTY) is True
        or wizard_facade.organization_has_detected_tool(
            organization_id=organization_id, kinds=[kind.value for kind in LLM_TOOL_KINDS]
        )
    )
    return OrganizationBridgeInputs(wizard=wizard)
