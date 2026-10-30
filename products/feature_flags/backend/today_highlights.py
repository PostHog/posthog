import re

from django.utils import timezone

from posthog.constants import PRODUCT_TOUR_TARGETING_FLAG_PREFIX, SURVEY_TARGETING_FLAG_PREFIX

from products.feature_flags.backend.facade.usage import (
    FLAG_CALL_DAYS,
    CreatedFlag,
    FlagCalls,
    list_flags_created_by,
    summarize_flag_calls,
)
from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel
from products.today.backend.facade.highlight_helpers import exact, human

REACH_DROP = "Flag ‘{flag}’ reached {pct}% fewer users in the last 7 days"
REACH_DROP_DETAIL = "{before} → {now} · Check the code that calls it"
UNUSED_ONE = "Flag ‘{flag}’ had no evaluations in the last 14 days"
UNUSED_ONE_DETAIL = "Delete it if no code uses it"
SAME_ONE = "Flag ‘{flag}’ is {value} for everyone"
SAME_ONE_DETAIL = "Remove it from the code, then delete it"
CLEANUP_MANY = "{n} of your flags are unused or the same for everyone"
CLEANUP_COST = "{n} of your flags were called {cost} times in the last 7 days"
CLEANUP_COST_DETAIL = "Same value for everyone: {names}"
AND_MORE = "{names} and {n} more"

INTERNAL_FLAG_PREFIXES = (SURVEY_TARGETING_FLAG_PREFIX, PRODUCT_TOUR_TARGETING_FLAG_PREFIX)
RISKY_FLAGS = re.compile(r"(?i)(kill|override|switch|disable|maintenance|remote-config)|-[0-9a-f]{8,}$")
MIN_REACH = 20
SAME_VALUE_MIN_AGE_DAYS = 30
CLEANUP_COST_MIN = 100_000
NO_CALLS = FlagCalls(
    people_this_week=0, people_last_week=0, calls_this_week=0, calls=0, values_this_week=0, value_this_week=None
)


def _reach_drop(flag: CreatedFlag, calls: FlagCalls) -> HighlightCandidate:
    return HighlightCandidate(
        key=f"flag_reach_drop:{flag.id}",
        label=HighlightLabel.RISK,
        family="flags",
        importance=0.6,
        relevance=1.0,
        title=REACH_DROP.format(
            flag=flag.key, pct=f"{(1 - calls.people_this_week / calls.people_last_week) * 100:.0f}"
        ),
        detail=REACH_DROP_DETAIL.format(now=exact(calls.people_this_week), before=exact(calls.people_last_week)),
        url=f"/feature_flags/{flag.id}",
    )


def _listing(keys: list[str]) -> str:
    names = ", ".join(keys[:3])
    return AND_MORE.format(names=names, n=len(keys) - 3) if len(keys) > 3 else names


def _cleanup(
    context: HighlightContext, removable: list[CreatedFlag], same: list[tuple[CreatedFlag, FlagCalls]]
) -> HighlightCandidate | None:
    if context.today.weekday() == 0 and removable:
        keys = [flag.key for flag in sorted(removable, key=lambda flag: flag.created_at)]
        if len(keys) > 1:
            title, detail = CLEANUP_MANY.format(n=len(keys)), _listing(keys)
        elif same:
            title = SAME_ONE.format(flag=keys[0], value=same[0][1].value_this_week or "false")
            detail = SAME_ONE_DETAIL
        else:
            title, detail = UNUSED_ONE.format(flag=keys[0]), UNUSED_ONE_DETAIL
    else:
        cost = sum(calls.calls_this_week for _, calls in same)
        if cost < CLEANUP_COST_MIN:
            return None
        title = CLEANUP_COST.format(n=len(same), cost=human(cost))
        detail = CLEANUP_COST_DETAIL.format(names=_listing([flag.key for flag, _ in same]))
    return HighlightCandidate(
        key="flag_cleanup",
        label=HighlightLabel.OPPORTUNITY,
        family="flag_cleanup",
        importance=0.3,
        relevance=1.0,
        title=title,
        detail=detail,
        url="/feature_flags",
    )


def find_flag_highlights(context: HighlightContext) -> HighlightFindings:
    flags = [
        flag
        for flag in list_flags_created_by(context.team.id, context.user.id, limit=500)
        if not flag.remote_configuration and not flag.key.startswith(INTERNAL_FLAG_PREFIXES)
    ]
    if not flags:
        return HighlightFindings()
    summary = context.daily("flag_calls", lambda: summarize_flag_calls(context.team, context.user))
    items: list[HighlightCandidate] = []
    removable: list[CreatedFlag] = []
    same: list[tuple[CreatedFlag, FlagCalls]] = []
    for flag in flags:
        calls = summary.by_key.get(flag.key, NO_CALLS)
        if calls.people_last_week >= MIN_REACH and calls.people_this_week <= calls.people_last_week / 2:
            items.append(_reach_drop(flag, calls))
        if flag.removal_blocked or RISKY_FLAGS.search(flag.key) or not summary.covers_all_environments:
            continue
        age = (context.today - timezone.localtime(flag.created_at, context.team.timezone_info).date()).days
        if age >= SAME_VALUE_MIN_AGE_DAYS and calls.people_this_week >= MIN_REACH and calls.values_this_week == 1:
            removable.append(flag)
            same.append((flag, calls))
        elif age >= FLAG_CALL_DAYS and calls.calls == 0 and summary.complete:
            removable.append(flag)
    if cleanup := _cleanup(context, removable, same):
        items.append(cleanup)
    return HighlightFindings(items=tuple(items))
