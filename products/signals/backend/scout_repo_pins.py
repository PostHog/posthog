"""The repositories a pinned scout may point its reports at.

`SignalScoutConfig.repositories` says which code a scout reads: the runner clones those repos into
the run's sandbox. Read as an allowlist, the same pin also bounds where the scout's findings may
land. A scout pinned to one repository researches that repository, so a report it files, and any
implementation task autostarted from that report, may only target a pinned repo. Without the bound,
repository selection is free to choose any repo the team's GitHub installation reaches, and the
autostarted task then writes code in a repository the scout never read — which is how research
built on private sources reaches an unrelated codebase.

An unpinned scout (the default; it reads the project over MCP and clones nothing) names no
repositories, so there is nothing to bound it by and selection stays free.

A pin is a decision a project admin or the scout's acting user records through the config API,
which validates it against the repos the team's GitHub installation can reach. It is not
agent-writable, so a bound derived from it cannot be widened from inside a run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.repo_corrections import sanitized_repository
from products.signals.backend.scout_authorship import resolve_authoring_scout_config_ids


def normalized_pin(repositories: Iterable[str] | None) -> list[str]:
    """The pin as comparable `owner/repo` names, dropping anything that fails the shape gate.

    The gate is `sanitized_repository`, the same one every stored repository passes through, so a
    pin and a selected repository are compared in one form.
    """
    if not repositories:
        return []
    return [name for name in (sanitized_repository(entry) for entry in repositories) if name is not None]


def repository_within_pin(repository: str | None, pinned: Sequence[str]) -> bool:
    """Whether a repository is one a scout with this pin may target.

    An empty pin allows everything: the scout named no repositories, so it is unbounded. A null
    repository is always allowed — a report with no target opens nothing.
    """
    if not pinned or repository is None:
        return True
    return sanitized_repository(repository) in set(pinned)


def repositories_within_pin(repositories: Iterable[str], pinned: Sequence[str]) -> list[str]:
    """The candidates a scout with this pin may be offered, in the order given."""
    return [name for name in repositories if repository_within_pin(name, pinned)]


def run_pinned_repositories(run: SignalScoutRun) -> list[str]:
    """The pin of the scout behind one run.

    Read from the config row rather than the run, because the pin is config a person edits and the
    run carries no copy of it. A run whose config was deleted (`scout_config` is SET_NULL) reads as
    unpinned: the bound is only as durable as the row that records it.
    """
    if run.scout_config is None:
        return []
    return normalized_pin(run.scout_config.repositories)


def report_pinned_repositories(*, team_id: int, report_id: str) -> list[str]:
    """The pin bounding one report, as the union of the pins of the scouts that authored it.

    Authorship, not touch: a scout that edited someone else's report is bounded by its own pin at
    the edit, and bounding the report by it as well would let an unpinned editor void the author's
    bound. A report no scout run authored (the pipeline path) has no pin.

    An unpinned co-author does not lift the bound either. The union runs over the pins that exist,
    so a report one pinned scout backs stays bounded by that scout's repositories — the conservative
    direction, since the pinned author's research is what the report is built from.

    `for_team`, not the ambient scope: the autostart caller runs in a Temporal activity, where the
    fail-closed manager has no request scope to read.
    """
    config_ids = resolve_authoring_scout_config_ids(team_id, report_id)
    pinned: set[str] = set()
    for repositories in (
        SignalScoutConfig.objects.for_team(team_id).filter(pk__in=config_ids).values_list("repositories", flat=True)
    ):
        pinned.update(normalized_pin(repositories))
    return sorted(pinned)
