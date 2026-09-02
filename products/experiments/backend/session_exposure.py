"""How a session-scoped experiment surface reads exposure.

The session buckets and the watch shelf both answer questions about "the sessions this experiment
exposed someone in", and both have to mean the same thing by it: which event carries the exposure,
which property carries the variant, and what to do when that event was only ever captured where
there is no session to record. Resolved once here, because two surfaces disagreeing on the
population would show up as one of them silently answering over a wider set of sessions than it
names.
"""

from dataclasses import dataclass
from typing import Optional

from django.db import models
from django.db.models.functions import Coalesce

from posthog.hogql import ast

from posthog.models import EventProperty
from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    build_exposure_event_conditions,
    get_exposure_event_and_property,
    resolve_default_exposure_event,
)
from products.experiments.backend.models.experiment import Experiment


def never_session_linked_events(team: Team, event_names: frozenset[str]) -> frozenset[str]:
    """Event names never ingested with a `$session_id` property — only ever captured server-side, so
    no recordings filter on them can match and no session-scoped surface can see them.

    The same `EventProperty` fact the taxonomy `seen_together` endpoint serves the tab, read directly
    so the verdict doesn't depend on the caller knowing to check.
    """
    if not event_names:
        return frozenset()
    seen = (
        EventProperty.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        )
        .filter(effective_project_id=team.project_id, event__in=sorted(event_names), property="$session_id")
        .values_list("event", flat=True)
        .distinct()
    )
    return event_names - frozenset(seen)


@dataclass(frozen=True)
class SessionExposure:
    """One experiment's exposure semantics, as a session-scoped surface has to read them."""

    team: Team
    experiment: Experiment
    # What this experiment's default exposure resolves to under the $experiment_exposure rollout.
    # Carried rather than re-resolved so every clause in one response agrees on the event, even if
    # the flag flips mid-request.
    default_exposure_event: str
    # None when the criteria name an action: an action can match several events, so there is no
    # single name to look up or to prune a query on.
    exposure_event: Optional[str]
    # Already resolved to the stand-in where the fallback applies, so use sites never re-derive it.
    variant_property: str
    # Of the names asked about, the ones never ingested with a `$session_id`.
    never_linked: frozenset[str]
    used_fallback: bool

    @property
    def is_unmatchable(self) -> bool:
        """True when the exposure event can never match a session and nothing stands in for it, so
        the surface has nothing to answer over.

        Only the default events have a stand-in. Custom criteria assert that something specific
        happened, which the stamped flag property doesn't imply, so falling back would answer over
        "the flag was active in this session" — a wider population than the criteria name.
        """
        return self.exposure_event in self.never_linked and not self.used_fallback

    def variant_value(self) -> ast.Expr:
        return ast.Call(name="toString", args=[ast.Field(chain=["properties", self.variant_property])])

    def condition(self, variant_keys: list[str]) -> ast.Expr:
        """Match expression for "this session exposed someone in one of these arms".

        The exposure criteria resolved through the shared helpers — the single seam that keeps these
        surfaces in sync with the analysis and with the player's session context. Rebuilt per use
        site: the HogQL resolver annotates ast nodes in place, so one instance can't appear in two
        clauses of the same query.
        """
        variant_condition = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=self.variant_value(),
            right=ast.Constant(value=variant_keys),
        )
        if self.used_fallback:
            # The default exposure event has only ever been captured server-side, so it can't match
            # a session. posthog-js stamps `$feature/<flag_key>` on every client event captured
            # after flags load, so the stamped property stands in — the same fallback the tab's list
            # uses. It means "the flag was active in this session", not "this is where they were
            # enrolled", and the variant is the flag's value per event rather than the exposure
            # response, so a re-bucketed returning person can land in either arm.
            return variant_condition
        conditions = [
            *build_exposure_event_conditions(
                self.experiment.exposure_criteria,
                self.team,
                self.experiment.feature_flag.key,
                default_exposure_event=self.default_exposure_event,
            ),
            variant_condition,
        ]
        return ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0]


def resolve_session_exposure(team: Team, experiment: Experiment, *, event_names: frozenset[str]) -> SessionExposure:
    """Resolve how this experiment's exposure reads on sessions.

    `event_names` are the surface's own events — its metrics' — looked up for session linkability in
    the same bounded `EventProperty` read as the exposure event's, so one query settles both which
    metrics a session can show and whether the exposure event can match a session at all.
    """
    flag_key = experiment.feature_flag.key
    default_exposure_event = resolve_default_exposure_event(team, experiment.start_date)
    exposure_event, variant_property = get_exposure_event_and_property(
        flag_key, experiment.exposure_criteria, default_exposure_event=default_exposure_event
    )
    never_linked = never_session_linked_events(
        team, event_names | ({exposure_event} if exposure_event is not None else frozenset())
    )
    # Both default exposure events mean "this user was enrolled via the flag", which the stamped
    # flag property implies too, so either can take the fallback.
    used_fallback = (
        exposure_event in (DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT) and exposure_event in never_linked
    )
    return SessionExposure(
        team=team,
        experiment=experiment,
        default_exposure_event=default_exposure_event,
        exposure_event=exposure_event,
        variant_property=f"$feature/{flag_key}" if used_fallback else variant_property,
        never_linked=never_linked,
        used_fallback=used_fallback,
    )
