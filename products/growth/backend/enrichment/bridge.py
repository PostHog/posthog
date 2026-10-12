"""Read the scoring inputs Clay still owns, off the organization group it writes.

The ICP score's revenue input has no first-party source, so while Clay runs in parallel we
read its own group property back and score on it. That keeps our scores bit-comparable with
Clay's on the orgs it also scores.

The formula's third Clay-owned input, its GitHub profile lookup, is deliberately NOT read
here: Clay never projects that column into PostHog at all (verified against live group and
person writes), so product-role orgs score 3 rather than 6 until v-next substitutes a
first-party signal.

Every read is best-effort in coverage but strict about failure: an org Clay never processed
simply has no properties (a real null, and Clay scored nothing for it either), whereas an
unreachable group store raises. Scoring an org on inputs we failed to fetch would write a
silently-too-low score, which is worse than writing none — so callers degrade to writing
firmographics without a score on a raise, and get another chance at the delayed recheck.

The wizard input does not come from a group property. It is read from the wizard's own scan
events, matched against this module's list of LLM tool kinds.
"""

import json
import dataclasses
from typing import Any, Optional

from django.conf import settings

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.models.group.util import get_group_by_key
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.team import Team
from posthog.utils import get_instance_region

from products.growth.backend.enrichment.writer import ORGANIZATION_GROUP_TYPE

CLAY_EST_REVENUE_PROPERTY = "icp_est_revenue"
CLAY_COMPANY_TYPE_PROPERTY = "icp_company_type"

# The wizard reports what it found in a codebase with this event, on the organization group.
WIZARD_SCAN_EVENT = "wizard: warehouse sources detected"
WIZARD_SCAN_LOOKBACK_DAYS = 365
# Tool kinds from the wizard's scan that mean the org builds with LLMs. This list is the scoring
# decision, so it lives here rather than in the wizard's tool catalog.
LLM_TOOL_KINDS: frozenset[str] = frozenset(
    {
        "Anthropic",
        "AssemblyAI",
        "Browserbase",
        "Cohere",
        "Deepgram",
        "E2B",
        "ElevenLabs",
        "Firecrawl",
        "FireworksAI",
        "Groq",
        "Helicone",
        "HuggingFace",
        "LangSmith",
        "Langfuse",
        "LlamaCloud",
        "Mem0",
        "MistralAI",
        "OpenAI",
        "OpenRouter",
        "Replicate",
        "TogetherAI",
        "Vellum",
        "WeightsAndBiases",
        "Zep",
    }
)
# The wizard's own dependency scan reports this feature when the code imports an LLM SDK.
LLM_DISCOVERED_FEATURE = "llm"


class OrganizationGroupTypeMissing(Exception):
    """The internal project has no `organization` group type — a config problem, not a null input."""


@dataclasses.dataclass(frozen=True)
class ClayBridgeInputs:
    """Clay-owned score inputs for one org. All None when Clay never processed it."""

    est_revenue: Optional[float] = None
    # Presence of the company-type key, not its coerced value — Clay fills that column on
    # essentially every row it writes, making raw key-presence a reliable ran/didn't-run signal.
    clay_processed: bool = False


@frozen
class WizardBridgeInputs:
    """Whether the wizard's codebase scans for one org found an LLM SDK. False when it never scanned."""

    ai_sdk_detected: bool = False


@frozen
class OrganizationBridgeInputs:
    clay: ClayBridgeInputs = dataclasses.field(default_factory=ClayBridgeInputs)
    wizard: WizardBridgeInputs = dataclasses.field(default_factory=WizardBridgeInputs)


def _numeric(value: Any) -> Optional[float]:
    # Clay writes this through capture, so it can arrive as a JSON number or a numeric string;
    # JS would coerce either in a `>` comparison, Python would raise on the string.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _organization_group_type_index(team: Team) -> int:
    for group_type in get_group_types_for_project(team.project_id):
        if group_type["group_type"] == ORGANIZATION_GROUP_TYPE:
            return int(group_type["group_type_index"])
    # get_group_types_for_project swallows lookup failures into an empty list, so "not found"
    # here can equally mean the mapping store was unreachable. Either way it is not a null input.
    raise OrganizationGroupTypeMissing(f"no `{ORGANIZATION_GROUP_TYPE}` group type on project {team.project_id}")


def read_organization_bridge_inputs(*, organization_id: str) -> OrganizationBridgeInputs:
    """Fetch score inputs from one organization-group read. Raises when the group store cannot be read."""
    # Clay only ever wrote to the US internal project, so outside US there is nothing to read —
    # skip the lookup entirely instead of querying a project the bridge never touched.
    if get_instance_region() != "US":
        return OrganizationBridgeInputs()
    # The internal project the enrichment group properties are projected onto, and the same one
    # the ProductLed_Outbound consumer reads them back from (ee/billing/dags/productled_outbound_targets.py).
    team = Team.objects.get(id=settings.GROWTH_ENRICHMENT_INTERNAL_TEAM_ID)
    group_type_index = _organization_group_type_index(team)
    wizard = WizardBridgeInputs(
        ai_sdk_detected=_wizard_found_llm_sdk(
            team=team, group_type_index=group_type_index, organization_id=organization_id
        )
    )
    group = get_group_by_key(team_id=team.id, group_type_index=group_type_index, group_key=organization_id)
    if group is None:
        return OrganizationBridgeInputs(wizard=wizard)

    properties = group.group_properties or {}
    return OrganizationBridgeInputs(
        clay=ClayBridgeInputs(
            est_revenue=_numeric(properties.get(CLAY_EST_REVENUE_PROPERTY)),
            clay_processed=CLAY_COMPANY_TYPE_PROPERTY in properties,
        ),
        wizard=wizard,
    )


def _string_list(value: Any) -> list[str]:
    # HogQL returns an array event property as its JSON text.
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _wizard_found_llm_sdk(*, team: Team, group_type_index: int, organization_id: str) -> bool:
    response = execute_hogql_query(
        parse_select(
            """
            SELECT properties.warehouse_source_kinds, properties.discovered_features
            FROM events
            WHERE event = {event}
                AND {organization} = {organization_id}
                AND timestamp > now() - toIntervalDay({lookback_days})
            LIMIT 1000
            """,
            placeholders={
                "event": ast.Constant(value=WIZARD_SCAN_EVENT),
                "organization": ast.Field(chain=[f"$group_{group_type_index}"]),
                "organization_id": ast.Constant(value=organization_id),
                "lookback_days": ast.Constant(value=WIZARD_SCAN_LOOKBACK_DAYS),
            },
        ),
        team,
        query_type="growth_enrichment_wizard_scans",
    )
    for kinds, features in response.results or []:
        if LLM_TOOL_KINDS.intersection(_string_list(kinds)) or LLM_DISCOVERED_FEATURE in _string_list(features):
            return True
    return False
