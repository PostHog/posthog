"""How a session-scoped experiment surface reads exposure.

The session buckets and the recordings list's in-session narrowing both answer questions about
"the sessions this experiment exposed someone in", and both have to mean the same thing by it:
which event carries the exposure, and which property carries the variant. Resolved once here,
because two surfaces disagreeing on the population would show up as one of them silently
answering over a wider set of sessions than it names.

The two surfaces agree on what exposure means and differ in what they require of the evidence,
which follows from what each promises the viewer. The buckets aggregate over a population, where
"the flag was active in this session" is a legitimate member, so the stamped ``$feature/<key>``
stand-in applies to them. The recordings list offers a jump to the moment of enrollment, which
only the exposure event itself can locate, so it requires :attr:`SessionExposure.is_seekable_evidence`.

The watch shelf reads the person-scoped exposed population through ``replay_linkage`` instead, so
it is not a reader of this seam beyond :func:`never_session_linked_events`.
"""

from dataclasses import dataclass
from typing import Optional

from django.db import models
from django.db.models.functions import Coalesce

from posthog.hogql import ast

from posthog.models import EventDefinition, EventProperty
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
    # The flag key with any soft-delete tombstone stripped, matching the key historical events
    # carry. A flag cleaned up after its experiment stopped is renamed to `<key>:deleted:<id>`, and
    # resolving conditions on that renamed key would match no session. Carried so `condition` and
    # the stamped fallback agree with the population query, which strips it the same way.
    flag_key: str
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

    @property
    def is_seekable_evidence(self) -> bool:
        """True when the evidence is the exposure event itself, so a recording carrying it contains
        the moment of enrollment. The stamped property only says the flag was active somewhere in the
        session, which a surface that offers a jump to the exposure cannot honor."""
        return not self.used_fallback

    def variant_value(self) -> ast.Expr:
        return ast.Call(name="toString", args=[ast.Field(chain=["properties", self.variant_property])])

    def condition(self, variant_keys: list[str]) -> ast.Expr:
        """Match expression for "this session exposed someone in one of these variants".

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
            # after flags load, so the stamped property stands in. It means "the flag was active in
            # this session", not "this is where they were enrolled", and the variant is the flag's
            # value per event rather than the exposure response, so a re-bucketed returning person
            # can land in either variant. Only the buckets read it: the tab's list refuses the
            # stand-in, because a list labelled "exposed in session" would silently widen.
            return variant_condition
        conditions = [
            *build_exposure_event_conditions(
                self.experiment.exposure_criteria,
                self.team,
                self.flag_key,
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
    # Strip any soft-delete tombstone: a flag cleaned up after its experiment stopped is renamed to
    # `<key>:deleted:<id>`, but historical events still carry the original key, so conditions and the
    # stamped fallback must resolve against it, the same key the population query uses.
    flag_key = experiment.feature_flag.key_without_tombstone()
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
        flag_key=flag_key,
        default_exposure_event=default_exposure_event,
        exposure_event=exposure_event,
        variant_property=f"$feature/{flag_key}" if used_fallback else variant_property,
        never_linked=never_linked,
        used_fallback=used_fallback,
    )


def exposure_event_unseen(exposure: SessionExposure) -> bool:
    """True when ingestion has never seen the exposure event, so nothing is known about it yet.

    Distinct from `never_linked`, which means the event is known and has never carried a session id.
    Ingestion claims an event definition's `last_seen_at` the first time it sees the event, and a
    definition declared before any capture carries a null one, so that column is what separates an
    event that has arrived from one only named. A project running its first experiment after the
    $experiment_exposure rollout has no definition for that event until ingestion catches up, and
    reads as permanently server-side without this.

    Not `EventProperty`: it indexes which properties appear on which event rather than recording the
    event, and ingestion drops `$feature/<key>` rows on purpose, so a custom exposure event captured
    with only the variant property it requires leaves no row at all.

    Its own query, and its own function rather than a field on the resolution above, so only the
    in-session availability verdict pays for it. A session-linked event is known by definition, so
    the read is skipped unless the event already landed in `never_linked`.
    """
    if exposure.exposure_event is None or exposure.exposure_event not in exposure.never_linked:
        return False
    return not (
        EventDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        )
        .filter(
            effective_project_id=exposure.team.project_id,
            name=exposure.exposure_event,
            last_seen_at__isnull=False,
        )
        .exists()
    )
