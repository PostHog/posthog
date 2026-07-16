"""Read the scoring inputs Clay still owns, off the organization group it writes.

Three of the ICP score's inputs have no first-party source yet, so while Clay runs in parallel
we read its own group properties back and score on them. That keeps `clay-parity-1` scores
bit-comparable with Clay's on the orgs it also scores.

Every read is best-effort in coverage but strict about failure: an org Clay never processed
simply has no properties (a real null, and Clay scored nothing for it either), whereas an
unreachable group store raises — scoring an org on inputs we failed to fetch would write a
silently-too-low score, which is worse than writing none.
"""

import dataclasses
from typing import Any, Optional

from posthog.models.group.util import get_group_by_key
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.team import Team

from products.growth.backend.enrichment.writer import ORGANIZATION_GROUP_TYPE

# The internal project the enrichment group properties are projected onto, and the same one
# the ProductLed_Outbound consumer reads them back from (ee/billing/dags/productled_outbound_targets.py).
INTERNAL_TEAM_ID = 2

CLAY_EST_REVENUE_PROPERTY = "icp_est_revenue"
CLAY_COMPANY_TYPE_PROPERTY = "icp_company_type"
# UNVERIFIED — confirm against the live group properties before this leaves draft. Clay's other
# score inputs are `icp_*` columns projected onto the organization group, but its GitHub lookup
# is a person-level column ("GitHub Profile URL") with no confirmed group-property counterpart.
# If it turns out never to be projected, product-role orgs cannot reach 6 and score 3 instead.
CLAY_GITHUB_PROFILE_PROPERTY = "icp_github_profile_url"


class OrganizationGroupTypeMissing(Exception):
    """The internal project has no `organization` group type — a config problem, not a null input."""


@dataclasses.dataclass(frozen=True)
class ClayBridgeInputs:
    """Clay-owned score inputs for one org. All None when Clay never processed it."""

    est_revenue: Optional[float] = None
    company_type: Optional[str] = None
    github_profile_url: Optional[str] = None


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


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _organization_group_type_index(team: Team) -> int:
    for group_type in get_group_types_for_project(team.project_id):
        if group_type["group_type"] == ORGANIZATION_GROUP_TYPE:
            return int(group_type["group_type_index"])
    # get_group_types_for_project swallows lookup failures into an empty list, so "not found"
    # here can equally mean the mapping store was unreachable. Either way it is not a null input.
    raise OrganizationGroupTypeMissing(f"no `{ORGANIZATION_GROUP_TYPE}` group type on project {team.project_id}")


def read_clay_bridge_inputs(*, organization_id: str) -> ClayBridgeInputs:
    """Fetch the Clay-written score inputs for one org. Raises if the group store can't be read."""
    team = Team.objects.get(id=INTERNAL_TEAM_ID)
    group = get_group_by_key(
        team_id=team.id,
        group_type_index=_organization_group_type_index(team),
        group_key=organization_id,
    )
    if group is None:
        return ClayBridgeInputs()

    properties = group.group_properties or {}
    return ClayBridgeInputs(
        est_revenue=_numeric(properties.get(CLAY_EST_REVENUE_PROPERTY)),
        company_type=_text(properties.get(CLAY_COMPANY_TYPE_PROPERTY)),
        github_profile_url=_text(properties.get(CLAY_GITHUB_PROFILE_PROPERTY)),
    )
