"""Resolve a digest audience to the Slack channel its merges are posted in.

Routing is config, and the config lives in the repositories rather than in this database. Nothing
here is stored: a run resolves, posts, and records where it went. Change a declaration and the next
morning's digest follows it.

The order is proximity, not alphabet. For an audience's merges that came from repository R:

1. A ``repo:`` audience takes the channel R declared under ``digest:`` in ``.stamphog/policy.yml``.
2. A team slug takes R's own root ``owners.yaml`` registry, read through ``posthog_owners``. A
   repository that carries a registry answers for its own pull requests completely, including by
   omission: a registry lists the teams whose derived name is wrong, so a slug missing from it
   means "the derived name is right" rather than "no opinion".
3. A repository carrying no registry inherits one, taking the first in a fixed order. This is the
   convenience layer: ``charts`` has no ownership metadata of its own, so ``logs`` still posts to
   ``#team-apm`` because the monorepo says so.
4. Otherwise the slug is matched against a same-named Slack channel, which is the derived
   ``#<slug>`` rule that a registry entry exists to override.

Step 2 answers by omission. This is what stops a peripheral repository from capturing a team it
does not own. Without it, one repository that declares a slug routes every other repository's
merges for that team, because no other repository declared anything.

Two repositories that declare one team is a scope, not a conflict. Each answers for its own merges.
One audience can therefore resolve to two channels in one run, and the digest partitions between
them (see logic/digest_runs.py). No merge is posted twice, and no declaration is discarded.
"""

from __future__ import annotations

from django.db import router
from django.db.models import Q

import structlog
from posthog_owners.resolver import Purpose, TeamChannel, team_channel, teams_registry
from posthog_owners.schema import TeamEntry

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration

from ..facade.enums import ChannelResolutionSource
from ..models import StamphogRepoConfig
from .audiences import REPO_AUDIENCE_PREFIX
from .digest_config import load_repo_digest_config
from .github_client import StamphogGitHubClient

logger = structlog.get_logger(__name__)

# The distributed-ownership registry lives only in the repo-root file (posthog_owners.schema).
_OWNERS_FILE_PATH = "owners.yaml"

# The digest is automation, so it asks the registry where automation posts rather than where the
# team's people are. That falls back to the people channel when a team never separates the two.
_CHANNEL_PURPOSE: Purpose = "notifications"

# Slack channel flags that mark a channel as shared beyond this workspace. Routing maps a GitHub
# team slug onto a Slack channel by name, or by a registry entry. A shared channel with that name
# therefore sends internal PR digests outside the workspace, which is a leak. is_ext_shared and
# is_pending_ext_shared cover live and pending external connections. is_shared also catches
# org-shared channels. A repo's own declared digest channel is exempt, because the maintainer chose
# that channel for their own repository.
_SHARED_CHANNEL_FLAGS = ("is_ext_shared", "is_pending_ext_shared", "is_shared")


class RoutingUnavailable(Exception):
    """A registry could not be read, so no routing decision this run is safe.

    Every run derives routing again, and nothing is cached. A half-read registry therefore does not
    degrade. It reroutes, and it does so silently. The repository whose ``owners.yaml`` fetch failed
    can be the one that declares every team's channel. A run that continues without it sends the
    morning's digests to derived channel names. One lost day costs less.
    """


@frozen
class SlackChannel:
    channel_id: str
    shared: bool


@frozen
class Destination:
    """Where one audience's merges from one repository go, and the workspace they go to.

    The integration rides along because a destination without it cannot be posted to, and the run
    row does not store it. Hashable, so the claim can group its merges by destination.
    """

    slack_integration_id: int
    channel_id: str
    channel_name: str
    source: ChannelResolutionSource


@frozen
class RoutingContext:
    """Everything a team's daily run needs to route, fetched once.

    Resolving an audience is then a dict lookup. The previous design paid one registry fetch per
    connected repository and one paginated Slack listing for every audience separately, and four
    of every five of those fetches were 404s against repositories that carry no ownership file.
    """

    slack_integration_id: int
    # Repository -> that repo's root registry. A repo carrying no registry maps to an empty mapping,
    # which is what makes it inherit rather than answer (see _registry_answer).
    registry_by_repo: dict[str, dict[str, TeamEntry]]
    # What a repo carrying no registry falls back to: the first non-empty one in repository order.
    # Resolved once here rather than searched per pull request, so the inherited answer is both a
    # lookup and reproducible when more than one repo declares the same slug.
    inherited_registry: dict[str, TeamEntry]
    # Repository -> the channel name it declared under digest: in .stamphog/policy.yml.
    declared_repo_channel: dict[str, str]
    channels_by_name: dict[str, SlackChannel]


def _is_shared_channel(channel: dict) -> bool:
    return any(channel.get(flag) for flag in _SHARED_CHANNEL_FLAGS)


def _candidate_repo_configs(team_id: int) -> list[StamphogRepoConfig]:
    """Every repo the team still uses, in a fixed order.

    Any of them can carry the root ``owners.yaml`` that names a team's channel. The run therefore
    reads all of them, rather than the repo that merged last. A team whose PRs arrive from several
    repos must not get a different channel because of merge timing. The order by repository makes
    the inherited answer reproducible when more than one repo declares the same slug.

    Reviews alone qualify a repo. The registry is ownership metadata, not digest configuration, so
    a monorepo that carries it stays the source for a deployment repo even with its own digest off.
    A repo switched off entirely is dropped, because nobody can correct it any more, and a dead
    installation would fail every routing context below.

    Writer pin: a repo connected seconds ago is a legitimate registry source, and a lagged reader
    dropping it would change the answer for that run only.
    """
    return list(
        StamphogRepoConfig.objects.for_team(team_id)
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(Q(enabled=True) | Q(digest_enabled=True))
        .order_by("repository")
    )


def _fetch_channel_map(integration: Integration) -> dict[str, SlackChannel]:
    """Public channel name -> channel, for one Slack integration.

    Private channels are skipped: listing them needs a real authed Slack user, and this runs from a
    background task with no request user to act as. Public-only is fine for name matching. The
    shared flag rides along rather than filtering here, because the repo-declared path is allowed
    to name a shared channel and the other paths are not.
    """
    return {
        channel["name"]: SlackChannel(channel_id=channel["id"], shared=_is_shared_channel(channel))
        for channel in SlackIntegration(integration).list_public_channels()
    }


@frozen
class _RepoRouting:
    """What one repository declares about routing: its team registry, and its own digest channel."""

    registry: dict[str, TeamEntry]
    declared_channel: str | None


def _read_repo_routing(repo_config: StamphogRepoConfig) -> _RepoRouting:
    """One repo's routing config: its root registry, and the digest channel it declared.

    Both reads answer to one failure contract. A transient fetch failure for either file raises
    RoutingUnavailable rather than reading as "this repo declares nothing", which is the silent
    reroute that class exists to prevent. An absent file is not a failure: a repo carrying no
    owners.yaml inherits one, and a repo declaring no channel has no repo audience to route.
    """
    try:
        raw = StamphogGitHubClient(repo_config.installation_id).get_default_branch_file(
            repo_config.repository, _OWNERS_FILE_PATH
        )
        digest_config = load_repo_digest_config(repo_config) if repo_config.digest_enabled else None
    except Exception as e:
        raise RoutingUnavailable(f"could not read routing config for {repo_config.repository}: {e}") from e

    return _RepoRouting(
        registry=teams_registry(raw) if raw is not None else {},
        declared_channel=digest_config.channel if digest_config is not None and digest_config.channel else None,
    )


def build_routing_context(team_id: int) -> RoutingContext | None:
    """Fetch everything the team's run needs to route. None when the team has no Slack integration.

    Raises ``RoutingUnavailable`` when a registry could not be read.
    """
    integration = Integration.objects.filter(team_id=team_id, kind="slack").first()
    if integration is None:
        logger.info("stamphog_routing_no_slack_integration", team_id=team_id)
        return None

    registry_by_repo: dict[str, dict[str, TeamEntry]] = {}
    declared_repo_channel: dict[str, str] = {}
    for repo_config in _candidate_repo_configs(team_id):
        routing = _read_repo_routing(repo_config)
        registry_by_repo[repo_config.repository] = routing.registry
        if routing.declared_channel is not None:
            declared_repo_channel[repo_config.repository] = routing.declared_channel

    try:
        channels_by_name = _fetch_channel_map(integration)
    except Exception as e:
        raise RoutingUnavailable(f"could not list Slack channels for team {team_id}: {e}") from e

    return RoutingContext(
        slack_integration_id=integration.id,
        registry_by_repo=registry_by_repo,
        # _candidate_repo_configs orders by repository, so this is the first carrier in that order.
        inherited_registry=next((registry for registry in registry_by_repo.values() if registry), {}),
        declared_repo_channel=declared_repo_channel,
        channels_by_name=channels_by_name,
    )


def _registry_answer(context: RoutingContext, slug: str, repository: str) -> TeamChannel:
    """What the closest registry says about this slug, for merges that came from ``repository``.

    A repository that holds a registry answers from that registry and never inherits one. This is
    what makes it answer by omission. ``team_channel`` reports an absent slug as undeclared, and the
    caller reads that as "the derived name is correct".

    An empty mapping means the repository carries no registry. It does not mean the repository
    carries an empty one. The difference only matters for a root file with an empty ``teams:``
    block, which no repository has a reason to write.
    """
    registry = context.registry_by_repo.get(repository) or context.inherited_registry
    return team_channel(slug, registry, _CHANNEL_PURPOSE)


def resolve_destination(context: RoutingContext, audience_key: str, repository: str) -> Destination | None:
    """Where this audience's merges from ``repository`` go, or None when they go nowhere.

    None covers three different situations that all mean "post nothing": a declaration silenced the
    audience, a declared channel does not exist in the workspace, and a derived name matched
    nothing. The caller leaves those merges unclaimed, so a declaration added later picks them up
    on a later run rather than losing them.
    """
    if audience_key.startswith(REPO_AUDIENCE_PREFIX):
        channel_name = context.declared_repo_channel.get(audience_key[len(REPO_AUDIENCE_PREFIX) :])
        if channel_name is None:
            return None
        # The maintainer named a destination for their own repository, shared or not. Their call.
        return _match(context, channel_name, ChannelResolutionSource.STAMPHOG_CONFIG, allow_shared=True)

    answer = _registry_answer(context, audience_key, repository)
    if answer.declared:
        if answer.channel is None:
            logger.info("stamphog_routing_silenced_by_config", audience_key=audience_key, repository=repository)
            return None
        # A registry entry can name a channel for a team the declaring repo does not own, so the
        # shared-channel guard stays on: an externally shared match here leaves the workspace.
        return _match(context, answer.channel, ChannelResolutionSource.OWNERS_CONTACT, allow_shared=False)

    # The derived #<slug>, which is the name a registry entry exists to override.
    return _match(context, audience_key, ChannelResolutionSource.SLACK_NAME_MATCH, allow_shared=False)


def _match(
    context: RoutingContext, channel_name: str, source: ChannelResolutionSource, *, allow_shared: bool
) -> Destination | None:
    name = channel_name.removeprefix("#")
    channel = context.channels_by_name.get(name)
    if channel is None:
        # A declared channel that is not there is a dead end, never a reason to retry the slug: the
        # slug is exactly the wrong name the declaration was written to correct.
        if source != ChannelResolutionSource.SLACK_NAME_MATCH:
            logger.info("stamphog_routing_declared_channel_not_found", channel_name=name, source=source)
        return None
    if channel.shared and not allow_shared:
        logger.info("stamphog_routing_shared_channel_skipped", channel_name=name, source=source)
        return None
    return Destination(
        slack_integration_id=context.slack_integration_id,
        channel_id=channel.channel_id,
        channel_name=name,
        source=source,
    )
