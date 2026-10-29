"""What a scanner's recording filter may hold, defined once for every path that accepts one.

A scanner keeps less of a recording filter than the replay list does, and each difference fails
silently: a dropped condition saves a scanner that watches more than the person chose, and a broken
one saves a scanner whose runs keep failing. Create, update, the estimate and the draft all accept a
filter, so they share these rules rather than each keeping a copy that can drift.
"""

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ValidationError as PydanticValidationError,
)
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import ActionsNode, FilterLogicalOperator, RecordingsQuery

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort

# A scanner's schedule owns time, so a saved filter never carries a date range.
DATE_FIELDS = ("date_from", "date_to")
# Only the replay list API resolves these. A scanner would keep them and never apply them, and watch
# more recordings than the filter shows.
REPLAY_LIST_ONLY_FIELDS = ("comment_text", "hide_viewed_recordings")
# Copied into every observation's snapshot, so the write boundary caps it.
MAX_QUERY_BYTES = 50_000

_FILTER_LISTS = ("properties", "events", "actions")


class ScannerQueryError(ValueError):
    """A recording filter a scanner cannot keep. The message is safe to show to the caller, and
    `field` names the request field it belongs to."""

    def __init__(self, message: str, *, field: str = "query") -> None:
        super().__init__(message)
        self.field = field


def _as_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScannerQueryError("Recording filter must be a JSON object.")
    return value


def _parsed(value: dict[str, Any]) -> RecordingsQuery:
    try:
        return RecordingsQuery.model_validate(value)
    except PydanticValidationError:
        raise ScannerQueryError("Recording filter is invalid.")


def combines_with_and(query: dict[str, Any] | None) -> bool:
    """Whether the query's conditions must all hold, so a condition ANDed onto it narrows it.

    Read from the parsed query the way the recordings query builder reads it: anything but `AND`,
    an explicit null included, joins the conditions with OR.
    """
    return query is None or _parsed(query).operand == FilterLogicalOperator.AND_


def clean_scanner_query(value: object) -> dict[str, Any]:
    """The filter as a scanner stores it: a valid `RecordingsQuery` without the date range.

    Raises `ScannerQueryError` for anything a saved scanner must not hold.
    """
    value = _as_object(value)
    _parsed(value)
    # Exposure is derived from experiment_targeting at scan time, never persisted in the query blob:
    # writable exposure there would bypass experiment_targeting's access check and let an editor run
    # the exposure filter under the creator's access.
    if value.get("experiment_exposure") is not None:
        raise ScannerQueryError(
            "Recording filter can't set experiment exposure directly. Set experiment_targeting instead."
        )
    cleaned = {key: item for key, item in value.items() if key not in DATE_FIELDS}
    if fields := replay_list_only_fields(cleaned):
        raise ScannerQueryError(
            f"A scanner can't apply these recording filters: {', '.join(fields)}. Remove them and try again."
        )
    if len(json.dumps(cleaned, separators=(",", ":")).encode()) > MAX_QUERY_BYTES:
        raise ScannerQueryError(f"Recording filter is too large. Keep it under {MAX_QUERY_BYTES // 1000} KB.")
    return cleaned


def replay_list_only_fields(query: dict[str, Any]) -> list[str]:
    """The fields set on `query` that only the replay list API resolves."""
    return [field for field in REPLAY_LIST_ONLY_FIELDS if query.get(field)]


def unresolved_references(
    query: dict[str, Any], team: Team, *, can_read_action: Callable[[Action], bool] = lambda action: True
) -> list[str]:
    """The actions and cohorts `query` names that a scan cannot load, described for the caller.

    Resolved the way the recordings query builder resolves them, by project and with deleted cohorts
    excluded, so a filter this accepts always builds. Without the check, the estimate fails the same
    way a timeout does, and a broken filter saves into a scanner whose runs keep failing.

    An action `can_read_action` refuses reads as unresolved too, so the result never tells a caller
    that an id they cannot read exists.
    """
    refs = query_references(query, team)
    action_ids = {ref for ref in refs.actions if isinstance(ref, int)}
    cohort_ids = {ref for ref in refs.cohorts if isinstance(ref, int)}
    found_actions = {
        action.id
        for action in Action.objects.filter(pk__in=action_ids, team__project_id=team.project_id)
        if can_read_action(action)
    }
    found_cohorts = set(
        Cohort.objects.filter(pk__in=cohort_ids, team__project_id=team.project_id, deleted=False).values_list(
            "id", flat=True
        )
    )
    missing_actions = [ref for ref in refs.actions if ref not in found_actions]
    missing_cohorts = [ref for ref in refs.cohorts if ref not in found_cohorts]
    return [f"action {ref}" for ref in missing_actions] + [f"cohort {ref}" for ref in missing_cohorts]


@frozen
class QueryReferences:
    """The ids a query names, in order and without repeats. A value that is not an integer id stays as
    it is, so it reads as unresolved."""

    actions: list[int | str]
    cohorts: list[int | str]
    # A HogQL filter can name actions and cohorts inside its expression, where they cannot be read
    # reliably, so a caller who cannot read both is refused one.
    hogql: bool = False


def query_references(query: dict[str, Any], team: Team) -> QueryReferences:
    """Every action and cohort id the query names, read from the filters the query builder runs.

    The builder reads typed filters, not the raw JSON: an untyped `{"value": 7}` is a cohort filter,
    an event entry of type `actions` is an action, and a property group nests its filters. Reading the
    same typed filters means a reference cannot run without being found here.
    """
    parsed = _parsed(query)
    try:
        builder = ReplayFiltersEventsSubQuery(team, parsed)
        entities = [*builder.entities, *builder.negated_entities]
    except (DRFValidationError, TypeError, ValueError):
        # Entities are untyped in the query, so a malformed one only fails when it is built.
        raise ScannerQueryError("Recording filter is invalid.")
    actions: dict[int | str, None] = {}
    cohorts: dict[int | str, None] = {}
    hogql = False

    def as_id(value: object) -> int | str:
        try:
            return int(value)  # type: ignore[call-overload]
        except (TypeError, ValueError, OverflowError):
            return str(value)

    def visit(item: object) -> None:
        nonlocal hogql
        if isinstance(item, BaseModel):
            item = item.model_dump(exclude_none=True)
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        if item.get("type") in ("cohort", "precalculated-cohort", "static-cohort"):
            cohorts[as_id(item.get("value"))] = None
        elif item.get("type") == "behavioral" and item.get("event_type") == "actions":
            actions[as_id(item.get("key"))] = None
        elif item.get("type") == "hogql":
            hogql = True
        # A property group holds its filters in `values`, and a filter can nest its own `properties`.
        visit(item.get("values"))
        visit(item.get("properties"))

    for entity in entities:
        if isinstance(entity, ActionsNode):
            actions[as_id(entity.id)] = None
        visit(entity.properties)
    visit(parsed.properties)
    visit(parsed.having_predicates)
    return QueryReferences(actions=list(actions), cohorts=list(cohorts), hogql=hogql)


class NarrowingRefusal(StrEnum):
    """Why conditions proposed for a chosen filter were not added to it."""

    # The operand covers the whole query, so an OR on either side would widen the scan, not narrow it.
    OR_OPERAND = "or_operand"
    # The combined filter breaks a rule a saved scanner must meet, such as the size cap.
    INVALID = "invalid"
    # The combined filter matched no recent recordings.
    MATCHED_NOTHING = "matched_nothing"
    # The combined filter could not be checked, so nothing shows it still matches recordings.
    UNVERIFIED = "unverified"


@frozen
class ChosenQueryNarrowing:
    """A chosen filter with proposed conditions ANDed onto it, or the reason they were not."""

    query: dict[str, Any]
    # The conditions that were added, which `query` already holds. None when nothing was added.
    additions: dict[str, Any] | None
    refusal: NarrowingRefusal | None


def narrow_chosen_query(chosen: dict[str, Any], proposed: dict[str, Any] | None) -> ChosenQueryNarrowing:
    """`chosen` with the conditions of `proposed` that it lacks ANDed onto it.

    The chosen filter is never removed or widened, so the scanner can only watch fewer recordings
    than the person picked. A condition `chosen` already holds is not added twice, and a proposal
    with nothing new is no proposal, so it is not refused either.
    """
    new = {
        key: [item for item in (proposed or {}).get(key) or [] if item not in (chosen.get(key) or [])]
        for key in _FILTER_LISTS
    }
    new = {key: items for key, items in new.items() if items}
    if not new:
        return ChosenQueryNarrowing(query=chosen, additions=None, refusal=None)
    if not combines_with_and(chosen) or not combines_with_and(proposed):
        return ChosenQueryNarrowing(query=chosen, additions=None, refusal=NarrowingRefusal.OR_OPERAND)
    combined = {**chosen, **{key: [*(chosen.get(key) or []), *items] for key, items in new.items()}}
    try:
        combined = clean_scanner_query(combined)
    except ScannerQueryError:
        return ChosenQueryNarrowing(query=chosen, additions=None, refusal=NarrowingRefusal.INVALID)
    return ChosenQueryNarrowing(query=combined, additions={"kind": "RecordingsQuery", **new}, refusal=None)


@frozen
class ChosenScope:
    """The scope a draft starts from: the filter as a scanner keeps it, and the experiment it watches."""

    query: dict[str, Any]
    experiment_id: int | None
    # The variants the person picked, or None for every variant. Set only by exposure in the filter.
    experiment_variants: list[str] | None
    # Whether the experiment came from exposure in the filter rather than an `experiment_id`.
    experiment_from_query: bool


def chosen_scope(value: object, *, experiment_id: int | None) -> ChosenScope:
    """The scope of a filter the person chose, as the replay list holds it.

    The replay list scopes a filter to an experiment with exposure inside the query, which a saved
    scanner keeps as its experiment instead. The whole filter is parsed first, so the exposure is read
    only once it is known to be well formed. A filter the scanner could keep only in part is refused,
    because the draft would then watch more than the person chose.
    """
    value = _as_object(value)
    exposure = _parsed(value).experiment_exposure
    query = clean_scanner_query({key: item for key, item in value.items() if key != "experiment_exposure"})
    if exposure is None:
        return ChosenScope(
            query=query, experiment_id=experiment_id, experiment_variants=None, experiment_from_query=False
        )
    # The replay list's exposure resolver refuses these, so the scope would be one it cannot honor.
    if exposure.variant is not None and exposure.variants is not None:
        raise ScannerQueryError("The experiment exposure can set 'variant' or 'variants', not both.")
    if exposure.variants is not None and not exposure.variants:
        raise ScannerQueryError("The experiment exposure's 'variants' must name at least one variant.")
    if exposure.in_session:
        raise ScannerQueryError("A scanner can't keep the in-session exposure condition. Remove it and try again.")
    if experiment_id is not None and experiment_id != exposure.experiment_id:
        raise ScannerQueryError("This is not the experiment the recording filter is scoped to.", field="experiment_id")
    # In order and without repeats, as the replay list resolves them: a scanner refuses repeated variants.
    variants = list(dict.fromkeys(exposure.variants or ([exposure.variant] if exposure.variant else []))) or None
    return ChosenScope(
        query=query,
        experiment_id=exposure.experiment_id,
        experiment_variants=variants,
        experiment_from_query=True,
    )
