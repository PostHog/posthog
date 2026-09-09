"""Seeders for the feature-flag lifecycle eval cases.

Each seeder runs once, in the case's own team, after the team is provisioned and
before the prompt is dispatched. What it returns lands in ``output["seed"]``, so
scorers read the seeded key, id and filters from there rather than restating them.

Flag keys are module constants because the prompt, the seeder and the scorers all
have to mean the same flag. Keys are invented Hedgebox-flavored product names that
the seeded dataset does not already use (see ``products/posthog_ai/evals/AGENTS.md``
for the flags it does).

Two seeders here change a policy rather than create data, and both verify the policy
took effect before returning. A policy that silently failed to apply would turn its
case into a hollow pass: the agent would face no restriction and score for handling
one. Raising instead marks the case an infra error, which the harness excludes from
score averages.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

from django.utils import timezone

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization

from products.access_control.backend.facade.mcp_access import mcp_access_denial
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.team_feature_flag_policy_config import (
    TeamFeatureFlagPolicyConfig,
    team_requires_flag_tags,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

__all__ = [
    "DEPENDENT_FLAG_KEY",
    "DISABLE_FLAG_KEY",
    "ENABLE_FLAG_KEY",
    "EXISTING_FLAG_FROM_PERCENTAGE",
    "EXISTING_FLAG_KEY",
    "EXISTING_FLAG_TO_PERCENTAGE",
    "METADATA_FLAG_KEY",
    "READ_ONLY_FLAG_KEY",
    "REQUIRED_TAGS_FLAG_KEY",
    "ROLLOUT_FLAG_KEY",
    "ROLLOUT_FROM_PERCENTAGE",
    "ROLLOUT_INITIAL_FILTERS",
    "ROLLOUT_PINNED_PERCENTAGE",
    "ROLLOUT_TO_PERCENTAGE",
    "STALE_FLAG_KEY",
    "STALE_FLAG_LAST_CALLED_DAYS_AGO",
    "seed_active_flag",
    "seed_existing_key_flag",
    "seed_inactive_flag",
    "seed_metadata_flag",
    "seed_read_only_mcp_org",
    "seed_require_flag_tags",
    "seed_rollout_flag",
    "seed_stale_flag",
]

METADATA_FLAG_KEY = "file-preview-thumbnails"
EXISTING_FLAG_KEY = "bulk-download-zip"
DISABLE_FLAG_KEY = "share-link-expiry"
ENABLE_FLAG_KEY = "folder-color-tags"
ROLLOUT_FLAG_KEY = "smart-upload-retry"
STALE_FLAG_KEY = "legacy-drag-drop-upload"
# The flag whose release condition points at the stale one. A scorer reads this key,
# so the answer has to name the blocker rather than any caveat it can think of.
DEPENDENT_FLAG_KEY = "upload-progress-toast"
READ_ONLY_FLAG_KEY = "team-audit-log"
# Nothing seeds this one: the case asks the agent to create it.
REQUIRED_TAGS_FLAG_KEY = "billing-sync-killswitch"

# The rollout the flag already holds, and the one the prompt asks for. The prompt and
# the scorer read the same constants, so a reworded prompt cannot leave the check
# grading the old request.
EXISTING_FLAG_FROM_PERCENTAGE = 20
EXISTING_FLAG_TO_PERCENTAGE = 30

ROLLOUT_FROM_PERCENTAGE = 10
ROLLOUT_TO_PERCENTAGE = 25
# The second release condition, which the rollout edit must leave alone.
ROLLOUT_PINNED_PERCENTAGE = 100

# Comfortably past the 30-day staleness threshold in `flag_status.py`, and relative to
# now so the case keeps meaning the same thing as time passes.
STALE_FLAG_LAST_CALLED_DAYS_AGO = 90

_BOOLEAN_FULL_ROLLOUT: dict[str, Any] = {"groups": [{"properties": [], "rollout_percentage": 100}]}

# The composite configuration a rollout edit can drop. Exported because
# `PreservedUnrelatedConfig`'s tests grade against this exact shape: a second copy would
# let them keep passing after the seeder changed.
ROLLOUT_INITIAL_FILTERS: dict[str, Any] = {
    "groups": [
        {
            "properties": [{"key": "plan", "type": "person", "value": ["business/enterprise"], "operator": "exact"}],
            "rollout_percentage": ROLLOUT_PINNED_PERCENTAGE,
        },
        {"properties": [], "rollout_percentage": ROLLOUT_FROM_PERCENTAGE},
    ],
    "multivariate": {
        "variants": [
            {"key": "control", "name": "Control", "rollout_percentage": 50},
            {"key": "retry", "name": "Retry", "rollout_percentage": 50},
        ]
    },
    "payloads": {"control": '{"attempts":0}', "retry": '{"attempts":3}'},
}


def _create_flag(
    context: CustomPromptSandboxContext,
    *,
    key: str,
    name: str,
    filters: dict[str, Any],
    active: bool = True,
) -> FeatureFlag:
    return FeatureFlag.objects.create(
        team_id=context.team_id,
        created_by_id=context.user_id,
        key=key,
        name=name,
        filters=filters,
        active=active,
    )


def _flag_payload(flag: FeatureFlag) -> dict[str, Any]:
    return {
        "feature_flag_id": flag.id,
        "feature_flag_key": flag.key,
        "feature_flag_name": flag.name,
        "initial_filters": flag.filters,
        "initial_active": flag.active,
    }


def seed_metadata_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """One flag with real targeting, for the rename-and-redescribe case.

    The targeting exists so the case can tell a metadata-only edit from one that
    also replaced `filters`.
    """
    flag = _create_flag(
        context,
        key=METADATA_FLAG_KEY,
        name="Thumbnail previews in the file browser",
        filters={
            "groups": [
                {
                    "properties": [
                        {"key": "plan", "type": "person", "value": ["business/standard"], "operator": "exact"}
                    ],
                    "rollout_percentage": 50,
                }
            ]
        },
    )
    return _flag_payload(flag)


def seed_existing_key_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """A flag already holding the key the prompt asks to create."""
    flag = _create_flag(
        context,
        key=EXISTING_FLAG_KEY,
        name="Download several files as one zip",
        filters={"groups": [{"properties": [], "rollout_percentage": EXISTING_FLAG_FROM_PERCENTAGE}]},
    )
    payload = _flag_payload(flag)
    # `PreservedUnrelatedConfig` reads these to tell the condition the prompt moves from
    # the ones it must leave alone. Without them every condition reads as pinned and a
    # correct write scores 0.
    payload["rollout_from_percentage"] = EXISTING_FLAG_FROM_PERCENTAGE
    payload["rollout_to_percentage"] = EXISTING_FLAG_TO_PERCENTAGE
    return payload


def seed_active_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """An enabled flag, for the turn-it-off case."""
    flag = _create_flag(
        context,
        key=DISABLE_FLAG_KEY,
        name="Expiring share links",
        filters=_BOOLEAN_FULL_ROLLOUT,
        active=True,
    )
    return _flag_payload(flag)


def seed_inactive_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """A disabled flag, for the turn-it-on case."""
    flag = _create_flag(
        context,
        key=ENABLE_FLAG_KEY,
        name="Color tags on folders",
        filters=_BOOLEAN_FULL_ROLLOUT,
        active=False,
    )
    return _flag_payload(flag)


def seed_rollout_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """A flag whose composite configuration a rollout edit can drop.

    Two release conditions, two variants and two payloads. The prompt asks for one
    number to move, and `filters` replaces the whole object, so everything else here
    is what `PreservedUnrelatedConfig` checks survived.
    """
    flag = _create_flag(
        context,
        key=ROLLOUT_FLAG_KEY,
        name="Retry a failed upload automatically",
        # Copied so the ORM does not hold a reference to the shared constant.
        filters=deepcopy(ROLLOUT_INITIAL_FILTERS),
    )
    payload = _flag_payload(flag)
    payload["rollout_from_percentage"] = ROLLOUT_FROM_PERCENTAGE
    payload["rollout_to_percentage"] = ROLLOUT_TO_PERCENTAGE
    return payload


def seed_stale_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """A flag that reads as stale, plus an active flag that depends on it.

    The staleness comes from usage: enabled, never archived, last evaluated well past
    the 30-day threshold in `flag_status.py`. The dependent flag is what makes the
    honest answer more than "stale, delete it" — removing this flag breaks another.
    """
    flag = _create_flag(
        context,
        key=STALE_FLAG_KEY,
        name="Drag and drop uploads (legacy path)",
        filters=_BOOLEAN_FULL_ROLLOUT,
        active=True,
    )
    FeatureFlag.objects.filter(pk=flag.pk).update(
        last_called_at=timezone.now() - timedelta(days=STALE_FLAG_LAST_CALLED_DAYS_AGO),
        created_at=timezone.now() - timedelta(days=STALE_FLAG_LAST_CALLED_DAYS_AGO * 2),
    )

    dependent = _create_flag(
        context,
        key=DEPENDENT_FLAG_KEY,
        name="Progress toast while a file uploads",
        filters={
            "groups": [
                {
                    "properties": [
                        {"key": str(flag.id), "type": "flag", "value": "true", "operator": "flag_evaluates_to"}
                    ],
                    "rollout_percentage": 100,
                }
            ]
        },
        active=True,
    )

    payload = _flag_payload(flag)
    payload["dependent_flag_key"] = dependent.key
    payload["last_called_days_ago"] = STALE_FLAG_LAST_CALLED_DAYS_AGO
    return payload


def seed_read_only_mcp_org(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Cap the case's organization to read-only MCP access, then prove the cap holds.

    `read_only_mcp_access` denies every write that arrives through the MCP server,
    admins included, which is the pathway the sandboxed agent uses. The feature has
    to be available for the cap to apply, so grant that first.
    """
    flag = _create_flag(
        context,
        key=READ_ONLY_FLAG_KEY,
        name="Per-team audit log",
        filters=_BOOLEAN_FULL_ROLLOUT,
        active=True,
    )

    # `Team.organization` sets related_query_name="team", so a filter spells it `team`
    # even though the accessor is `organization.teams`.
    organization = Organization.objects.get(team__id=context.team_id)
    features = list(organization.available_product_features or [])
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS):
        features.append(
            {
                "key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
                "name": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS,
            }
        )
    organization.available_product_features = features
    organization.read_only_mcp_access = True
    organization.save(update_fields=["available_product_features", "read_only_mcp_access"])

    denial = mcp_access_denial(organization, is_mcp=True, writes=True)
    if not denial:
        raise RuntimeError(
            "read_only_mcp_access did not deny an MCP write for this organization, so the case "
            "would score the agent for handling a restriction it never met. Check whether "
            "products/access_control/backend/facade/mcp_access.py still gates on "
            f"{AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}."
        )

    payload = _flag_payload(flag)
    payload["expected_denial"] = denial
    return payload


def seed_require_flag_tags(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Turn on the project's "require tags on new flags" policy, then prove it is on.

    Nothing else is seeded: the case asks the agent to create a flag, and the policy
    is what it has to notice.
    """
    TeamFeatureFlagPolicyConfig.objects.update_or_create(team_id=context.team_id, defaults={"require_tags": True})
    if not team_requires_flag_tags(context.team_id):
        raise RuntimeError(
            "the require-tags policy did not stick for this team, so the case would score the "
            "agent for recovering from an error the API never returns. Check "
            "products/feature_flags/backend/models/team_feature_flag_policy_config.py."
        )

    return {"feature_flag_key": REQUIRED_TAGS_FLAG_KEY, "requires_tags": True}
