"""Auto-provision a Slack DigestChannel for a digest audience.

Channel destination is auto-resolved, never pre-created by a human. Three ways an audience finds
its channel, in order:

1. A "repo:" audience matches the channel its repo declared under `digest:` in
   `.stamphog/policy.yml` (see logic/digest_config.py).
2. A team slug matches the channel the repo's root `owners.yaml` declares for it, read through
   ``posthog_owners`` so the registry's semantics live in one place. This is what routes a team
   whose channel isn't named after its slug — `logs` posts to `#team-apm`, not `#logs`.
3. Otherwise the slug is matched against a same-named Slack channel, which is the derived
   `#<slug>` rule the registry above exists to override.

Humans only ever correct or disable rows afterward — see models.DigestChannel and
logic/audiences.py for how the audience_key itself is produced.
"""

from __future__ import annotations

from typing import cast

from django.db import IntegrityError, router

import structlog
from posthog_owners.resolver import TeamChannel, team_channel, teams_registry

from posthog.models.integration import Integration, SlackIntegration

from ..facade.enums import ChannelResolutionSource
from ..models import DigestChannel, PullRequestAudience, StamphogRepoConfig
from .digest_config import load_repo_digest_config
from .github_client import StamphogGitHubClient

logger = structlog.get_logger(__name__)

_REPO_AUDIENCE_PREFIX = "repo:"

# The distributed-ownership registry lives only in the repo-root file (posthog_owners.schema).
_OWNERS_FILE_PATH = "owners.yaml"

# Slack channel flags that mark a channel as shared beyond this workspace. Auto-provisioning maps a
# GitHub team/author slug onto a same-named Slack channel, so a shared channel matching that name would
# route internal PR digests into an externally connected (Slack Connect) or cross-org channel — a leak.
# is_ext_shared / is_pending_ext_shared cover live and pending external connections; is_shared also
# catches org-shared channels. A repo-DECLARED digest channel is exempt (the maintainer chose it).
_SHARED_CHANNEL_FLAGS = ("is_ext_shared", "is_pending_ext_shared", "is_shared")


def _is_shared_channel(channel: dict) -> bool:
    return any(channel.get(flag) for flag in _SHARED_CHANNEL_FLAGS)


def _fetch_channel_map(integration: Integration, *, exclude_shared: bool) -> dict[str, dict[str, str]]:
    """Public channel name -> {"id": ..., "name": ...} for one Slack integration.

    Private channels are skipped: listing them needs a real authed Slack user, and this runs from
    a background task with no request user to act as — public-only is fine for name matching.
    When ``exclude_shared`` (the name-match auto-provision path), externally/org-shared channels are
    dropped too so a digest can never be routed into a channel another org can see (see
    _SHARED_CHANNEL_FLAGS). A repo-declared channel is looked up with ``exclude_shared=False`` — the
    maintainer named it explicitly, so a shared target there is their deliberate choice.
    """
    authed_user = cast(str, (integration.config or {}).get("authed_user", {}).get("id") or "")
    channels = SlackIntegration(integration).list_channels(
        should_include_private_channels=False, authed_user=authed_user
    )
    return {
        channel["name"]: {"id": channel["id"], "name": channel["name"]}
        for channel in channels
        if not (exclude_shared and _is_shared_channel(channel))
    }


def _declared_repo_channel_name(team_id: int, audience_key: str) -> str | None:
    """For a "repo:" audience_key, the Slack channel name its repo declared under ``digest:`` in
    ``.stamphog/policy.yml`` — checked before any Slack API call, so an undeclared repo costs one
    GitHub file fetch, not a Slack channel list. None if the repo isn't configured, isn't
    digest-enabled, or hasn't declared a channel.
    """
    repository = audience_key[len(_REPO_AUDIENCE_PREFIX) :]
    # Writer pin: this gate decides an enabled channel plus the immediate Slack post — a lagged
    # reader returning a stale digest_enabled=True row would post a digest the user just opted out of.
    repo_config = (
        StamphogRepoConfig.objects.for_team(team_id)
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(repository=repository, digest_enabled=True)
        .first()
    )
    if repo_config is None:
        return None
    digest_config = load_repo_digest_config(repo_config)
    if digest_config is None or not digest_config.channel:
        return None
    return digest_config.channel


def _audience_repo_config(team_id: int, audience_key: str) -> StamphogRepoConfig | None:
    """A repo whose merges produced this audience — the source of the ownership that named it.

    Writer pin: the audience rows are written at merge capture, which can be seconds before the
    digest runs. A lagged reader returning nothing here silently downgrades a declared channel to
    a name match, which is the mapping the registry exists to correct.

    Several repos can feed one team's audience and the newest wins. DigestChannel is keyed on
    (team, audience) alone, so whichever provisions first decides; two repos disagreeing about one
    team's channel is not something this resolves.
    """
    audience = (
        PullRequestAudience.objects.for_team(team_id)
        .using(router.db_for_write(PullRequestAudience))
        .filter(audience_key=audience_key)
        .select_related("pull_request__repo_config")
        .order_by("-created_at")
        .first()
    )
    return audience.pull_request.repo_config if audience is not None else None


def _declared_team_channel(team_id: int, audience_key: str) -> TeamChannel | None:
    """The channel the repo's ``owners.yaml`` registry declares for this team slug, or None.

    None means nothing declared one — no repo behind the audience, no ownership file, or no entry
    for the slug — which leaves the caller on the name-match path. That path already implements the
    registry's own derived ``#<slug>`` rule, so there is nothing to gain by returning a derivation
    here, and something to lose: a derived name must stay a guess that a human confirms.
    """
    repo_config = _audience_repo_config(team_id, audience_key)
    if repo_config is None:
        return None
    try:
        raw = StamphogGitHubClient(repo_config.installation_id).get_default_branch_file(
            repo_config.repository, _OWNERS_FILE_PATH
        )
    except Exception:
        # Provisioning is retried every run, so a GitHub blip costs a day, not a wrong channel.
        logger.warning(
            "stamphog_channel_resolution_owners_fetch_failed",
            team_id=team_id,
            audience_key=audience_key,
            exc_info=True,
        )
        return None
    if raw is None:
        return None
    declared = team_channel(audience_key, teams_registry(raw))
    return declared if declared.declared else None


def resolve_slack_destination(
    team_id: int, audience_key: str
) -> tuple[int, dict[str, str], ChannelResolutionSource] | None:
    """Find the Slack channel destination for ``audience_key`` in the team's workspace.

    Resolves through the three steps in the module docstring, stopping at the first that answers.
    Returns (slack_integration_id, {"id": ..., "name": ...}, source) on a match, None otherwise.
    """
    if audience_key.startswith(_REPO_AUDIENCE_PREFIX):
        channel_name = _declared_repo_channel_name(team_id, audience_key)
        if channel_name is None:
            return None
        resolution_source = ChannelResolutionSource.STAMPHOG_CONFIG
    elif (declared := _declared_team_channel(team_id, audience_key)) is not None:
        if declared.channel is None:
            # `slack: false` — the team declared it has no channel. An answer, not a gap, so this
            # must not fall through to a name match on the slug.
            logger.info(
                "stamphog_channel_resolution_team_declares_no_channel", team_id=team_id, audience_key=audience_key
            )
            return None
        channel_name = declared.channel.removeprefix("#")
        resolution_source = ChannelResolutionSource.OWNERS_CONTACT
    else:
        channel_name = audience_key
        resolution_source = ChannelResolutionSource.SLACK_NAME_MATCH

    integration = Integration.objects.filter(team_id=team_id, kind="slack").first()
    if integration is None:
        return None

    # A repo-declared channel is the maintainer naming a destination for their own repo's digest,
    # shared or not — their call. The other two paths route a team the declaring repo may not own
    # (a name match by slug, or a registry entry naming a channel for someone else), so they keep
    # the guard: an externally shared match there would leak the digest out of the workspace.
    exclude_shared = resolution_source != ChannelResolutionSource.STAMPHOG_CONFIG

    # Fetched fresh per provisioning attempt: only never-seen audiences get here (at most a handful
    # a day), so a paginated list per attempt is fine — a Slack hiccup just retries tomorrow.
    try:
        channel_map = _fetch_channel_map(integration, exclude_shared=exclude_shared)
    except Exception:
        logger.warning("stamphog_channel_resolution_list_channels_failed", team_id=team_id, exc_info=True)
        return None

    channel = channel_map.get(channel_name)
    if channel is None:
        # A declared channel that isn't there is a dead end, never a reason to retry the slug: the
        # slug is exactly the wrong name the declaration was written to correct.
        if resolution_source != ChannelResolutionSource.SLACK_NAME_MATCH:
            logger.info(
                "stamphog_channel_resolution_declared_channel_not_found",
                team_id=team_id,
                audience_key=audience_key,
                channel_name=channel_name,
                resolution_source=resolution_source,
            )
        return None
    return integration.id, channel, resolution_source


def auto_provision_channel(team_id: int, audience_key: str) -> DigestChannel | None:
    """Create a DigestChannel for (team, audience_key) if a Slack destination resolves.

    Repo-declared channels (``digest:`` in .stamphog config, read from the default branch) are the
    maintainer's explicit pick and provision enabled. A bare name match provisions DISABLED, pending
    a human enable in the UI: any workspace member can create a public channel named after a GitHub
    team slug, so auto-posting to a name-matched channel would let a squatter receive private repo
    titles and summaries.

    No-op (returns None, logged) when: the team has no Slack integration, no channel name
    matches, or a row already exists for this (team, audience_key) — including a disabled one,
    since disabled means a human opted out (or hasn't confirmed a name match yet) and
    auto-provisioning must never resurrect it.
    """
    if DigestChannel.objects.for_team(team_id).filter(audience_key=audience_key).exists():
        logger.info("stamphog_channel_resolution_row_exists", team_id=team_id, audience_key=audience_key)
        return None

    destination = resolve_slack_destination(team_id, audience_key)
    if destination is None:
        logger.info("stamphog_channel_resolution_no_match", team_id=team_id, audience_key=audience_key)
        return None
    slack_integration_id, channel, resolution_source = destination

    try:
        row = DigestChannel.objects.for_team(team_id).create(
            team_id=team_id,
            audience_key=audience_key,
            slack_integration_id=slack_integration_id,
            slack_channel_id=channel["id"],
            slack_channel_name=channel["name"],
            enabled=resolution_source != ChannelResolutionSource.SLACK_NAME_MATCH,
            resolution_source=resolution_source,
        )
    except IntegrityError:
        # Lost a create race — another concurrent provisioning attempt, or a human row landed
        # in between the existence check above and this create. Nothing lost.
        logger.info("stamphog_channel_resolution_race_lost", team_id=team_id, audience_key=audience_key)
        return None

    logger.info(
        "stamphog_channel_resolution_provisioned",
        team_id=team_id,
        audience_key=audience_key,
        slack_channel_id=channel["id"],
    )
    return row
