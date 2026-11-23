"""Manual-run Dagster job that records which partner application minted each provisioned personal API key.

Keys minted before `PersonalAPIKey.provisioned_by` existed carry no link to the partner, so the
partner's rotate, remove, and revoke paths cannot find them. This job sets `provisioned_by` on the
existing keys that match what the provisioning mint produces. It never deletes a key.

Run it from the Dagster UI with `dry_run: true` (the default) first, check the logged counts and
ambiguous keys, then run it again with `dry_run: false`.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping
from uuid import UUID

from django.db.models import Q

import dagster

from posthog.dags.common import JobOwners
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_provisioning import OrganizationProvisioning
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

KEY_BATCH_SIZE = 1000
PROVISIONED_LABEL_SEPARATOR = " - "
LABEL_MAX_LENGTH = PersonalAPIKey._meta.get_field("label").max_length or 0
ISSUES_PERSONAL_API_KEY_FILTER = Q(_provisioning_config__issues_personal_api_key=True)


def label_matches_provisioned_pattern(label: str, team_name: str) -> bool:
    """Whether the provisioning mint could have produced `label` for a team named `team_name`.

    The mint labels a key `<label_prefix> - <team name>` or the bare team name, truncated to the
    column length. The prefix is free text, so every separator in the label is tried as the split.
    """
    if label == team_name[:LABEL_MAX_LENGTH]:
        return True

    separator_index = label.find(PROVISIONED_LABEL_SEPARATOR)
    while separator_index > 0:
        prefix = label[:separator_index]
        if f"{prefix}{PROVISIONED_LABEL_SEPARATOR}{team_name}"[:LABEL_MAX_LENGTH] == label:
            return True
        separator_index = label.find(PROVISIONED_LABEL_SEPARATOR, separator_index + 1)

    return False


def matching_provisioning_apps(
    *,
    label: str,
    team_name: str,
    user_in_team_organization: bool,
    team_app_ids: Collection[UUID],
) -> frozenset[UUID]:
    """The partner applications that could have minted a key scoped to exactly one team.

    One application means the key gets tagged, none means it is left alone, and more than one
    means the key is ambiguous and is skipped.
    """
    if not user_in_team_organization or not label_matches_provisioned_pattern(label, team_name):
        return frozenset()

    return frozenset(team_app_ids)


def _team_app_ids(app_ids: Collection[UUID]) -> dict[int, set[UUID]]:
    """Map each team to the partner applications that provisioned it or its organization."""
    team_app_ids: dict[int, set[UUID]] = defaultdict(set)

    for team_id, app_id in TeamProvisioningConfig.objects.filter(application_id__in=app_ids).values_list(
        "team_id", "application_id"
    ):
        team_app_ids[team_id].add(app_id)

    organization_app_ids: dict[UUID, set[UUID]] = defaultdict(set)
    for organization_id, app_id in OrganizationProvisioning.objects.filter(application_id__in=app_ids).values_list(
        "organization_id", "application_id"
    ):
        organization_app_ids[organization_id].add(app_id)

    for team_id, organization_id in Team.objects.filter(organization_id__in=organization_app_ids).values_list(
        "id", "organization_id"
    ):
        team_app_ids[team_id] |= organization_app_ids[organization_id]

    return team_app_ids


def _user_organization_pairs(user_ids: Collection[int], organization_ids: Collection[UUID]) -> set[tuple[int, UUID]]:
    return set(
        OrganizationMembership.objects.filter(user_id__in=user_ids, organization_id__in=organization_ids).values_list(
            "user_id", "organization_id"
        )
    )


class TagProvisionedPersonalAPIKeysConfig(dagster.Config):
    dry_run: bool = True


@dagster.op
def tag_provisioned_personal_api_keys(
    context: dagster.OpExecutionContext, config: TagProvisionedPersonalAPIKeysConfig
) -> None:
    """Set `provisioned_by` on existing keys that a partner application minted during provisioning."""
    app_names: Mapping[UUID, str] = dict(
        OAuthApplication.objects.filter(ISSUES_PERSONAL_API_KEY_FILTER).values_list("id", "name")
    )
    context.log.info(f"Partner applications that mint personal API keys: {app_names}")

    team_app_ids = _team_app_ids(app_names.keys())
    teams: dict[int, tuple[str, UUID]] = {
        team_id: (name, organization_id)
        for team_id, name, organization_id in Team.objects.filter(id__in=team_app_ids).values_list(
            "id", "name", "organization_id"
        )
    }

    tagged_per_app: dict[UUID, int] = defaultdict(int)
    ambiguous_keys: list[tuple[str, int, list[str]]] = []

    unlinked_single_team_keys = PersonalAPIKey.objects.filter(
        provisioned_by__isnull=True, scoped_teams__len=1
    ).order_by("id")
    last_id = ""
    while batch := list(
        unlinked_single_team_keys.filter(id__gt=last_id).values_list("id", "user_id", "label", "scoped_teams")[
            :KEY_BATCH_SIZE
        ]
    ):
        last_id = batch[-1][0]

        candidates = [(key_id, user_id, label, scoped_teams[0]) for key_id, user_id, label, scoped_teams in batch]
        candidates = [candidate for candidate in candidates if candidate[3] in teams]
        memberships = _user_organization_pairs(
            {user_id for _, user_id, _, _ in candidates},
            {teams[team_id][1] for _, _, _, team_id in candidates},
        )

        key_ids_per_app: dict[UUID, list[str]] = defaultdict(list)
        for key_id, user_id, label, team_id in candidates:
            team_name, organization_id = teams[team_id]
            app_ids = matching_provisioning_apps(
                label=label,
                team_name=team_name,
                user_in_team_organization=(user_id, organization_id) in memberships,
                team_app_ids=team_app_ids[team_id],
            )

            if len(app_ids) > 1:
                ambiguous_keys.append((key_id, team_id, sorted(str(app_id) for app_id in app_ids)))
            elif app_ids:
                key_ids_per_app[next(iter(app_ids))].append(key_id)

        for app_id, key_ids in key_ids_per_app.items():
            if config.dry_run:
                tagged_per_app[app_id] += len(key_ids)
            else:
                tagged_per_app[app_id] += PersonalAPIKey.objects.filter(
                    id__in=key_ids, provisioned_by__isnull=True
                ).update(provisioned_by_id=app_id)

    verb = "Would tag" if config.dry_run else "Tagged"
    for app_id, count in tagged_per_app.items():
        context.log.info(f"{verb} {count} personal API keys for {app_names[app_id]} ({app_id})")
    for key_id, team_id, ambiguous_app_ids in ambiguous_keys:
        context.log.warning(f"Skipped ambiguous personal API key {key_id} on team {team_id}: apps {ambiguous_app_ids}")

    context.add_output_metadata(
        {
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
            "tagged_per_app": dagster.MetadataValue.json(
                {f"{app_names[app_id]} ({app_id})": count for app_id, count in tagged_per_app.items()}
            ),
            "tagged_total": dagster.MetadataValue.int(sum(tagged_per_app.values())),
            "ambiguous_total": dagster.MetadataValue.int(len(ambiguous_keys)),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_GROWTH.value})
def tag_provisioned_personal_api_keys_job():
    tag_provisioned_personal_api_keys()
