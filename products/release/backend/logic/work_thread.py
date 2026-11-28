"""The work thread of one release: its stages as an ordered line of steps, and what to do next.

A port of the release rules in `products/release/frontend/releaseUtils.ts` (the facts, the stage, the lifecycle,
`releaseNextStep` and `releaseSuggestions`). Keep both in step: the release page and the work thread must agree on
what a release needs next.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote, urlencode
from uuid import UUID

from posthog.dataclasses import frozen

from products.today.backend.facade.contracts import (
    WorkFact,
    WorkHelper,
    WorkItem,
    WorkLine,
    WorkOption,
    WorkRun,
    WorkStep,
    WorkThread,
)
from products.today.backend.facade.enums import WorkHelperMode, WorkOptionKind, WorkRunType

from ..facade.contracts import (
    LinkedBroadcastDTO,
    LinkedInsightDTO,
    LinkedSurveyDTO,
    ReleaseDTO,
    ReleaseFlagDetails,
    WorkEarlyAccessFeature,
    WorkExperiment,
    WorkFlag,
)

AREA = "Release"
REVIEW_AFTER_DAYS = 14
SCHEDULE_ROLLOUT_ACTION = "schedule_rollout"
# Changing a release needs editor access to feature flags, as on the release page.
LINK_FLAG_GATE = "You need editor access to feature flags to link a flag."
CREATE_FLAG_GATE = "You need editor access to feature flags to create a flag."
ADD_METRIC_GATE = "You need editor access to feature flags to add a metric."
ADD_SURVEY_GATE = "You need editor access to feature flags to add a survey."

Stage = Literal["planned", "flag", "experiment", "early_access", "released", "ended"]
LifecycleKey = Literal["planned", "flag", "testing", "released"]

_LIFECYCLE: tuple[LifecycleKey, ...] = ("planned", "flag", "testing", "released")
_STAGE_INDEX: dict[Stage, int] = {
    "planned": 0,
    "flag": 1,
    "experiment": 2,
    "early_access": 2,
    "released": 3,
    "ended": 3,
}

_ENROLLING_EARLY_ACCESS_STAGES = frozenset({"alpha", "beta"})
_PRELAUNCH_EARLY_ACCESS_STAGES = frozenset({"draft", "concept"})
_EARLY_ACCESS_NEXT = {
    "draft": "Launch early access",
    "concept": "Open the beta",
    "alpha": "Move to beta",
    "beta": "Move to general availability",
}
_CONCLUSION_LABEL = {
    "won": "The test variant won",
    "lost": "The test variant lost",
    "inconclusive": "The result was inconclusive",
    "stopped_early": "It was stopped early",
    "invalid": "The result was marked invalid",
}
_EXPERIMENT_STATUS_LABEL = {
    "draft": "Draft",
    "running": "Running",
    "paused": "Paused",
    "exposure_frozen": "Running",
    "stopped": "Complete",
}


@frozen
class ReleaseWorkFacts:
    """Everything the rules read about one release, as the viewer may see it.

    `now` carries the team's time zone, so dates read as they do on the release page.
    """

    release: ReleaseDTO
    details: ReleaseFlagDetails
    now: datetime
    can_edit: bool


@frozen
class _Audience:
    flag: WorkFlag
    percent: float | None
    who: str
    summary: str


@frozen
class _NextStep:
    key: str
    title: str
    detail: str
    item: WorkItem | None
    label: str | None = None
    to: str | None = None
    schedule_flag_id: int | None = None
    secondary_label: str | None = None
    secondary_to: str | None = None
    # Set for a rule with no primary action yet: the option that opens later, and the button it will carry.
    later_label: str | None = None
    later_run_label: str | None = None
    later_why: str | None = None


@frozen
class _Copy:
    headline: str
    detail: str


@frozen
class _Facts:
    release: ReleaseDTO
    now: datetime
    can_edit: bool
    flags: tuple[WorkFlag, ...]
    unloaded_flag_ids: tuple[int, ...]
    has_hidden_flags: bool
    complete: bool
    experiments: tuple[WorkExperiment, ...]
    early_access: tuple[WorkEarlyAccessFeature, ...]
    drafts: tuple[WorkExperiment, ...]
    done: tuple[WorkExperiment, ...]
    running: tuple[WorkExperiment, ...]
    paused: tuple[WorkExperiment, ...]
    open_early_access: WorkEarlyAccessFeature | None
    prelaunch_early_access: WorkEarlyAccessFeature | None
    ended: bool
    released: bool
    current: WorkExperiment | None
    running_days: int
    last_done: WorkExperiment | None
    audiences: tuple[_Audience, ...]
    audience_summary: str | None
    first_flag_created: datetime | None

    @property
    def finished(self) -> bool:
        return self.released or self.ended


def release_href(release_id: UUID | str) -> str:
    return f"/releases/{release_id}"


def flag_href(flag_id: int | str) -> str:
    return f"/feature-flags/{flag_id}"


def experiment_href(experiment_id: int | str) -> str:
    return f"/experiments/{experiment_id}"


def early_access_href(feature_id: UUID | str) -> str:
    return f"/early_access_features/{feature_id}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _day(moment: datetime, now: datetime) -> str:
    local = moment.astimezone(now.tzinfo)
    return f"{local.day} {local.strftime('%b')}"


def _js_round(value: float) -> float:
    return math.floor(value + 0.5)


def _is_draft(experiment: WorkExperiment) -> bool:
    return experiment.status == "draft"


def _is_paused(experiment: WorkExperiment) -> bool:
    return experiment.status == "paused"


def _is_done(experiment: WorkExperiment) -> bool:
    return experiment.status == "stopped" or experiment.end_date is not None


def _is_running(experiment: WorkExperiment) -> bool:
    return not _is_draft(experiment) and not _is_paused(experiment) and not _is_done(experiment)


def _is_enrolling(feature: WorkEarlyAccessFeature) -> bool:
    return feature.stage in _ENROLLING_EARLY_ACCESS_STAGES


def _rollout(percentage: float | None) -> float:
    return 100 if percentage is None else percentage


def _is_fully_rolled_out(flag: WorkFlag) -> bool:
    if not flag.active or not flag.is_v1_config:
        return False
    if flag.feature_enrollment or flag.holdout_exclusion_percentage > 0:
        return False
    conditions = flag.conditions
    if any(
        condition.aggregation_group_type_index is not None
        and condition.aggregation_group_type_index != flag.aggregation_group_type_index
        for condition in conditions
    ):
        return False
    open_indexes = [index for index, condition in enumerate(conditions) if not condition.property_count]
    if flag.early_exit:
        reaches_everyone = bool(open_indexes) and all(
            _rollout(condition.rollout_percentage) == 100 for condition in conditions[: open_indexes[0] + 1]
        )
    else:
        reaches_everyone = any(
            not condition.property_count and _rollout(condition.rollout_percentage) == 100 for condition in conditions
        )
    if not flag.variants:
        return reaches_everyone
    winner = next((variant for variant in flag.variants if variant.rollout_percentage == 100), None)
    return (
        reaches_everyone
        and winner is not None
        and all(not condition.variant or condition.variant == winner.key for condition in conditions)
    )


def _can_widen_rollout(flag: WorkFlag) -> bool:
    return flag.is_v1_config and not flag.feature_enrollment and not _is_fully_rolled_out(flag)


def _condition_audience(flag: WorkFlag, opt_in: bool) -> _Audience:
    if not flag.active:
        return _Audience(
            flag=flag, percent=0, who="Nobody, the flag is disabled", summary="The flag is disabled, so nobody gets it"
        )
    if not flag.is_v1_config:
        return _Audience(flag=flag, percent=None, who="Rules decide", summary="The flag rules decide who gets it")
    conditions = flag.conditions
    if opt_in and all(_rollout(condition.rollout_percentage) == 0 for condition in conditions):
        return _Audience(
            flag=flag,
            percent=None,
            who="Only users who opt in",
            summary="Only users who opt in through early access get it",
        )
    if len(conditions) == 1:
        condition = conditions[0]
        percent = _rollout(condition.rollout_percentage)
        filter_count = condition.property_count
        group_type = (
            condition.aggregation_group_type_index
            if condition.aggregation_group_type_index is not None
            else flag.aggregation_group_type_index
        )
        noun = "groups" if group_type is not None else "users"
        matching = f"{noun} that match {filter_count} filter{'s' if filter_count > 1 else ''}"
        return _Audience(
            flag=flag,
            percent=percent,
            who=matching[0].upper() + matching[1:] if filter_count else f"All {noun}",
            summary=f"{_number(percent)}% of {matching}" if filter_count else f"{_number(percent)}% of all {noun}",
        )
    return _Audience(
        flag=flag,
        percent=None,
        who=f"{len(conditions)} condition sets",
        summary=f"{len(conditions)} condition sets decide who gets it",
    )


def _flag_audience(flag: WorkFlag, opt_in: bool) -> _Audience:
    audience = _condition_audience(flag, opt_in)
    holdout = flag.holdout_exclusion_percentage
    if not holdout:
        return audience
    return _Audience(
        flag=flag,
        percent=None if audience.percent is None else _js_round(audience.percent * (100 - holdout)) / 100,
        who=audience.who,
        summary=f"{audience.summary}, except a {_number(holdout)}% holdout",
    )


def _first[T](items: Iterable[T], matches: Callable[[T], bool]) -> T | None:
    return next((item for item in items if matches(item)), None)


def _facts(work: ReleaseWorkFacts) -> _Facts:
    release, details = work.release, work.details
    flags_by_id = {flag.id: flag for flag in details.flags}
    flags = tuple(flags_by_id[flag_id] for flag_id in release.feature_flag_ids if flag_id in flags_by_id)
    unloaded = tuple(flag_id for flag_id in release.feature_flag_ids if flag_id not in flags_by_id)
    complete = not release.has_hidden_flags and not any(flag.id in details.incomplete_flag_ids for flag in flags)
    experiments = tuple(
        experiment
        for flag in flags
        for experiment in details.experiments
        if experiment.feature_flag_key == flag.key and (not experiment.archived or _is_done(experiment))
    )
    early_access = tuple(
        feature for flag in flags for feature in details.early_access_features if feature.feature_flag_id == flag.id
    )
    running = tuple(experiment for experiment in experiments if _is_running(experiment))
    done = tuple(experiment for experiment in experiments if _is_done(experiment))
    paused = tuple(experiment for experiment in experiments if _is_paused(experiment))
    drafts = tuple(experiment for experiment in experiments if _is_draft(experiment))
    open_early_access = _first(early_access, _is_enrolling)
    current = min(running, key=lambda experiment: experiment.start_date or work.now, default=None)
    first_start = current.start_date if current else None
    opt_in_flag_ids = {feature.feature_flag_id for feature in early_access if _is_enrolling(feature)}
    audiences = tuple(_flag_audience(flag, flag.id in opt_in_flag_ids or flag.feature_enrollment) for flag in flags)
    summaries = {audience.summary for audience in audiences}
    if len(summaries) > 1:
        audience_summary: str | None = (
            f"{sum(1 for audience in audiences if _is_fully_rolled_out(audience.flag))} of {len(audiences)} flags reach everyone"
            if all(audience.percent is not None for audience in audiences)
            else f"Differs across {len(audiences)} flags"
        )
    else:
        audience_summary = audiences[0].summary if audiences else None
    ended = bool(flags) and not unloaded and not release.has_hidden_flags and all(flag.archived for flag in flags)
    released = (
        not ended
        and complete
        and bool(flags)
        and not unloaded
        and all(_is_fully_rolled_out(flag) for flag in flags)
        and not running
        and not paused
        and not drafts
        and open_early_access is None
    )
    return _Facts(
        release=release,
        now=work.now,
        can_edit=work.can_edit,
        flags=flags,
        unloaded_flag_ids=unloaded,
        has_hidden_flags=release.has_hidden_flags,
        complete=complete,
        experiments=experiments,
        early_access=early_access,
        drafts=drafts,
        done=done,
        running=running,
        paused=paused,
        open_early_access=open_early_access,
        prelaunch_early_access=None
        if open_early_access
        else _first(early_access, lambda feature: feature.stage in _PRELAUNCH_EARLY_ACCESS_STAGES),
        ended=ended,
        released=released,
        current=current,
        running_days=(work.now - first_start).days + 1 if first_start else 0,
        last_done=max(done, key=lambda experiment: experiment.end_date or datetime.min.replace(tzinfo=work.now.tzinfo))
        if done
        else None,
        audiences=audiences,
        audience_summary=audience_summary,
        first_flag_created=min((flag.created_at for flag in flags), default=None),
    )


def _stage(facts: _Facts) -> Stage:
    if facts.ended:
        return "ended"
    if facts.released:
        return "released"
    if facts.running or facts.paused or facts.drafts or facts.done:
        return "experiment"
    if facts.open_early_access:
        return "early_access"
    return "flag" if facts.flags or facts.has_hidden_flags else "planned"


def _last_done_copy(last_done: WorkExperiment, now: datetime) -> _Copy:
    if last_done.conclusion:
        comment = f" {last_done.conclusion_comment}" if last_done.conclusion_comment else ""
        detail = f"{_CONCLUSION_LABEL.get(last_done.conclusion, last_done.conclusion)}.{comment}"
    else:
        detail = "No result is recorded on the experiment yet."
    return _Copy(
        headline=f"Experiment ended on {_day(last_done.end_date, now)}" if last_done.end_date else "Experiment stopped",
        detail=detail,
    )


def _copy(facts: _Facts) -> _Copy:
    if facts.ended:
        return _Copy(
            headline="Release ended", detail="The flags of this release are archived, so it no longer changes."
        )
    if facts.released:
        return _Copy(headline="Rolled out to all users", detail="Every flag of this release serves it to everyone.")
    if facts.running and facts.current and facts.current.start_date:
        days = facts.running_days
        return _Copy(
            headline=f"Experiment running for {days} day{'' if days == 1 else 's'}",
            detail=f"Started on {_day(facts.current.start_date, facts.now)}. "
            "Results are worth reading after about two weeks.",
        )
    if facts.paused:
        return _Copy(
            headline="Experiment paused", detail=f"{facts.paused[0].name} is paused, so it collects no new data."
        )
    if facts.drafts:
        return _Copy(
            headline="Experiment ready to launch", detail=f"{facts.drafts[0].name} is in draft. Nobody is in it yet."
        )
    if facts.last_done:
        return _last_done_copy(facts.last_done, facts.now)
    if facts.open_early_access:
        return _Copy(
            headline=f"In early access, {facts.open_early_access.stage}",
            detail="Users can opt in to it before everyone gets it.",
        )
    if facts.flags:
        summary = facts.audience_summary
        return _Copy(headline=summary[0].upper() + summary[1:] if summary else "Behind a flag", detail="")
    if facts.has_hidden_flags:
        return _Copy(
            headline="Behind flags you cannot see", detail="You do not have access to the flags of this release."
        )
    return _Copy(headline="Not started", detail="Link the feature flag that controls who gets this release.")


def _release_item(release: ReleaseDTO) -> WorkItem:
    return WorkItem(
        type="release",
        id=str(release.id),
        name=release.name,
        kind_label="release",
        product="Releases",
        href=release_href(release.id),
    )


def _flag_item(flag: WorkFlag) -> WorkItem:
    return WorkItem(
        type="feature_flag",
        id=str(flag.id),
        name=flag.key,
        kind_label="flag",
        product="Feature flags",
        href=flag_href(flag.id),
    )


def _experiment_item(experiment: WorkExperiment) -> WorkItem:
    return WorkItem(
        type="experiment",
        id=str(experiment.id),
        name=experiment.name,
        kind_label="experiment",
        product="Experiments",
        href=experiment_href(experiment.id),
    )


def _early_access_item(feature: WorkEarlyAccessFeature) -> WorkItem:
    return WorkItem(
        type="early_access_feature",
        id=str(feature.id),
        name=feature.name,
        kind_label="early access feature",
        product="Early access",
        href=early_access_href(feature.id),
    )


def _experiment_next_step(facts: _Facts) -> _NextStep | None:
    if facts.drafts and not facts.running:
        draft = facts.drafts[0]
        return _NextStep(
            key=f"launch-experiment:{draft.id}",
            title="Launch the experiment",
            detail=f"{draft.name} is ready. Launch it to start collecting results.",
            item=_experiment_item(draft),
            label="Open experiment",
            to=experiment_href(draft.id),
        )
    current = facts.current
    if current and facts.running_days >= REVIEW_AFTER_DAYS - 2:
        return _NextStep(
            key=f"review-results:{current.id}",
            title="Review the results",
            detail=f"{current.name} has {facts.running_days} days of data. Decide if the test variant should ship.",
            item=_experiment_item(current),
            label="Open results",
            to=experiment_href(current.id),
        )
    if current and current.start_date:
        review_on = _day(current.start_date + timedelta(days=REVIEW_AFTER_DAYS), facts.now)
        return _NextStep(
            key=f"review-results:{current.id}",
            title="Let the experiment run",
            detail=f"Check the results around {review_on}, when it has two weeks of data.",
            item=_experiment_item(current),
            secondary_label="Open experiment",
            secondary_to=experiment_href(current.id),
            later_label="Review the results",
            later_run_label="Open results",
            later_why=f"{current.name} has {facts.running_days} day{'' if facts.running_days == 1 else 's'} of data.",
        )
    if facts.paused:
        paused = facts.paused[0]
        return _NextStep(
            key=f"resume-or-end-experiment:{paused.id}",
            title="Resume or end the experiment",
            detail=f"{paused.name} is paused. Resume it to collect more data, or end it and record the result.",
            item=_experiment_item(paused),
            label="Open experiment",
            to=experiment_href(paused.id),
        )
    last_done = facts.last_done
    if last_done and not facts.finished and not last_done.conclusion:
        return _NextStep(
            key=f"record-result:{last_done.id}",
            title="Record the result",
            detail=f"{last_done.name} ended without a recorded result. Record it so the team knows what to ship.",
            item=_experiment_item(last_done),
            label="Open experiment",
            to=experiment_href(last_done.id),
        )
    return None


def _rollout_next_step(facts: _Facts) -> _NextStep | None:
    prelaunch = facts.prelaunch_early_access
    if not facts.finished and prelaunch:
        return _NextStep(
            key=f"early-access:{prelaunch.id}:{prelaunch.stage}",
            title=_EARLY_ACCESS_NEXT[prelaunch.stage],
            detail=f"{prelaunch.name} is in {prelaunch.stage}, so nobody can opt in yet.",
            item=_early_access_item(prelaunch),
            label="Open early access",
            to=early_access_href(prelaunch.id),
        )
    widen = None if facts.finished or facts.open_early_access else _first(facts.flags, _can_widen_rollout)
    if widen:
        return _NextStep(
            key=f"schedule-rollout:{widen.id}",
            title="Roll out the winner" if facts.last_done else "Roll out to more users",
            detail=f"Not everyone gets the winning variant yet. Roll {widen.key} out to all users now or on a date."
            if facts.last_done
            else f"Not everyone gets it yet. Widen the release conditions of {widen.key}, "
            "or schedule a rollout to everyone.",
            item=_flag_item(widen),
            label="Schedule rollout",
            schedule_flag_id=widen.id,
            secondary_label="Open flag",
            secondary_to=flag_href(widen.id),
        )
    open_early_access = facts.open_early_access
    if open_early_access and open_early_access.stage in _EARLY_ACCESS_NEXT:
        return _NextStep(
            key=f"early-access:{open_early_access.id}:{open_early_access.stage}",
            title=_EARLY_ACCESS_NEXT[open_early_access.stage],
            detail=f"{open_early_access.name} is in {open_early_access.stage}. Move it on when the feedback is good.",
            item=_early_access_item(open_early_access),
            label="Open early access",
            to=early_access_href(open_early_access.id),
        )
    if facts.released:
        return _NextStep(
            key=f"clean-up-flag:{facts.flags[0].id}",
            title="Clean up the flag",
            detail="Everyone gets the release now. Remove the flag check from your code, then archive the flag.",
            item=_flag_item(facts.flags[0]),
            label="Open flag",
            to=flag_href(facts.flags[0].id),
        )
    return None


def _release_next_step(facts: _Facts) -> _NextStep | None:
    if not facts.flags and not facts.has_hidden_flags:
        return _NextStep(
            key="link-flag",
            title="Link a feature flag",
            detail="Pick the flag your code checks for this change, or create one.",
            item=_release_item(facts.release),
        )
    if not facts.complete:
        return None
    return _experiment_next_step(facts) or _rollout_next_step(facts)


def _flag_fields(flag: WorkFlag, facts: _Facts) -> list[WorkFact]:
    audience = _first(facts.audiences, lambda candidate: candidate.flag.id == flag.id)
    fields = [WorkFact(label="Flag", value=flag.key)]
    if audience:
        fields.append(WorkFact(label="Who gets it", value=audience.summary))
    return fields


def _experiment_fields(experiment: WorkExperiment, facts: _Facts) -> list[WorkFact]:
    fields = [
        WorkFact(label="Experiment", value=experiment.name),
        WorkFact(label="Status", value=_EXPERIMENT_STATUS_LABEL.get(experiment.status, experiment.status)),
    ]
    if experiment.start_date:
        fields.append(WorkFact(label="Started", value=_day(experiment.start_date, facts.now)))
    if facts.current and facts.current.id == experiment.id:
        fields.append(WorkFact(label="Days running", value=str(facts.running_days)))
    if experiment.end_date:
        fields.append(WorkFact(label="Ended", value=_day(experiment.end_date, facts.now)))
    return fields


def _early_access_fields(feature: WorkEarlyAccessFeature) -> list[WorkFact]:
    return [WorkFact(label="Early access", value=feature.name), WorkFact(label="Stage", value=feature.stage)]


def _link_option(
    *,
    key: str,
    kind: WorkOptionKind,
    label: str,
    why: str,
    product: str,
    does: str,
    fields: list[WorkFact],
    run_label: str,
    to: str,
    mcp_tools: list[str],
    gate: str | None = None,
) -> WorkOption:
    return WorkOption(
        key=key,
        kind=kind,
        label=label,
        why=why,
        gate=gate,
        helper=WorkHelper(
            mode=WorkHelperMode.OPENS,
            product=product,
            does=does,
            fields=fields,
            run_label=run_label,
            run=WorkRun(type=WorkRunType.LINK, to=to),
            mcp_tools=mcp_tools,
        ),
    )


def _experiment_option(step: _NextStep, experiment: WorkExperiment, facts: _Facts) -> WorkOption:
    key = step.key.split(":")[0]
    does, mcp_tools = {
        "launch-experiment": ("Opens the experiment, where you can launch it.", ["experiment-launch"]),
        "review-results": (
            "Opens the experiment results, where you can ship a variant or end the experiment.",
            ["experiment-get", "experiment-ship-variant", "experiment-end"],
        ),
        "resume-or-end-experiment": (
            "Opens the experiment, where you can resume it or end it.",
            ["experiment-resume", "experiment-end"],
        ),
        "record-result": ("Opens the experiment, where you can record its result.", ["experiment-update"]),
    }[key]
    if step.later_label and step.later_run_label and step.later_why:
        return _link_option(
            key=step.key,
            kind=WorkOptionKind.NEXT,
            label=step.later_label,
            why=step.later_why,
            gate=step.detail,
            product="Experiments",
            does=does,
            fields=_experiment_fields(experiment, facts),
            run_label=step.later_run_label,
            to=experiment_href(experiment.id),
            mcp_tools=mcp_tools,
        )
    return _link_option(
        key=step.key,
        kind=WorkOptionKind.NEXT,
        label=step.title,
        why=step.detail,
        product="Experiments",
        does=does,
        fields=_experiment_fields(experiment, facts),
        run_label=step.label or "Open experiment",
        to=step.to or experiment_href(experiment.id),
        mcp_tools=mcp_tools,
    )


def _next_options(step: _NextStep, facts: _Facts) -> list[WorkOption]:
    if step.key == "link-flag":
        fields = [WorkFact(label="Release", value=facts.release.name)]
        return [
            _link_option(
                key="link-flag",
                kind=WorkOptionKind.NEXT,
                label=step.title,
                why=step.detail,
                product="Releases",
                does="Opens the release, where you can find the flag and link it.",
                fields=fields,
                run_label="Find a flag",
                to=release_href(facts.release.id),
                mcp_tools=["release-update"],
                gate=None if facts.can_edit else LINK_FLAG_GATE,
            ),
            _link_option(
                key="create-flag",
                kind=WorkOptionKind.NEXT,
                label="Create a flag",
                why=step.detail,
                product="Feature flags",
                does="Opens a new feature flag. Link it to this release once it is saved.",
                fields=fields,
                run_label="Create a flag",
                to=flag_href("new"),
                mcp_tools=["create-feature-flag"],
                gate=None if facts.can_edit else CREATE_FLAG_GATE,
            ),
        ]
    item = step.item
    if item is None:
        return []
    if item.type == "experiment":
        experiment = _first(facts.experiments, lambda candidate: str(candidate.id) == item.id)
        return [_experiment_option(step, experiment, facts)] if experiment else []
    if item.type == "early_access_feature":
        feature = _first(facts.early_access, lambda candidate: str(candidate.id) == item.id)
        if feature is None:
            return []
        return [
            _link_option(
                key=step.key,
                kind=WorkOptionKind.NEXT,
                label=step.title,
                why=step.detail,
                product="Early access",
                does="Opens the early access feature, where you can change its stage.",
                fields=_early_access_fields(feature),
                run_label=step.label or "Open early access",
                to=step.to or early_access_href(feature.id),
                mcp_tools=["early-access-feature-partial-update"],
            )
        ]
    flag = _first(facts.flags, lambda candidate: str(candidate.id) == item.id)
    if flag is None:
        return []
    if step.schedule_flag_id is not None:
        fields = _flag_fields(flag, facts)
        schedule = WorkOption(
            key=step.key,
            kind=WorkOptionKind.NEXT,
            label=step.title,
            why=step.detail,
            helper=WorkHelper(
                mode=WorkHelperMode.IN_PLACE,
                product="Feature flags",
                does=f"Schedules {flag.key} to roll out to all users, now or on a date you pick.",
                fields=fields,
                run_label=step.label or "Schedule rollout",
                run=WorkRun(
                    type=WorkRunType.ACTION,
                    action_id=SCHEDULE_ROLLOUT_ACTION,
                    params={"flag_id": step.schedule_flag_id},
                ),
                mcp_tools=["scheduled-changes-create"],
            ),
        )
        widen = _link_option(
            key=f"widen-rollout:{flag.id}",
            kind=WorkOptionKind.NEXT,
            label=f"Widen the release conditions of {flag.key}",
            why=step.detail,
            product="Feature flags",
            does="Opens the flag, where you can change who gets it.",
            fields=fields,
            run_label=step.secondary_label or "Open flag",
            to=step.secondary_to or flag_href(flag.id),
            mcp_tools=["feature-flag-roll-out-to-everyone", "feature-flag-set-release-condition-rollout"],
        )
        return [schedule, widen]
    return [
        _link_option(
            key=step.key,
            kind=WorkOptionKind.NEXT,
            label=step.title,
            why=step.detail,
            product="Feature flags",
            does="Opens the flag, where you can archive it once your code no longer checks it.",
            fields=_flag_fields(flag, facts),
            run_label=step.label or "Open flag",
            to=step.to or flag_href(flag.id),
            mcp_tools=["feature-flag-archive"],
        )
    ]


def _broadcast_new_href(release: ReleaseDTO) -> str:
    params = urlencode(
        {"name": release.name, "source": "release", "source_record": f"release:{release.id}"}, quote_via=quote
    )
    return f"/broadcasts/new?{params}"


def _alongside_options(facts: _Facts, stage: Stage) -> list[WorkOption]:
    release = facts.release
    options: list[WorkOption] = []
    if not release.metric_insight_ids:
        options.append(
            _link_option(
                key="metric",
                kind=WorkOptionKind.ALONGSIDE,
                label="Add a metric from a saved insight",
                why="Pick the saved insights that tell you whether this release works, then set a goal for each.",
                product="Releases",
                does="Opens the release, where you can pick a saved insight as a metric and set its goal.",
                fields=[WorkFact(label="Release", value=release.name)],
                run_label="Add a metric",
                to=release_href(release.id),
                mcp_tools=["release-update"],
                gate=None if facts.can_edit else ADD_METRIC_GATE,
            )
        )
    if not facts.complete or not facts.flags or facts.ended or stage in ("planned", "ended"):
        return options
    has_surveys = bool(release.survey_ids)
    flag_fields = [WorkFact(label="Flag", value=facts.flags[0].key)]

    def experiment() -> WorkOption:
        return _link_option(
            key="experiment",
            kind=WorkOptionKind.ALONGSIDE,
            label="Measure the impact",
            why="Run an experiment on this flag.",
            product="Experiments",
            does="Opens a new experiment. Pick the flag of this release to test it.",
            fields=flag_fields,
            run_label="New experiment",
            to=experiment_href("new"),
            mcp_tools=["experiment-create"],
        )

    def early_access() -> WorkOption:
        return _link_option(
            key="early-access",
            kind=WorkOptionKind.ALONGSIDE,
            label="Let users opt in early",
            why="Offer it as an early access feature.",
            product="Early access",
            does="Opens a new early access feature, so users can opt in before everyone gets it.",
            fields=flag_fields,
            run_label="New early access feature",
            to=early_access_href("new"),
            mcp_tools=["early-access-feature-create"],
        )

    def survey(audience: str) -> WorkOption:
        return _link_option(
            key="survey",
            kind=WorkOptionKind.ALONGSIDE,
            label="Ask what they think",
            why=f"A short survey for {audience}.",
            product="Surveys",
            does="Opens a new survey. Link it to this release once it is saved.",
            fields=flag_fields,
            run_label="New survey",
            to="/surveys/new",
            mcp_tools=["survey-create"],
            gate=None if facts.can_edit else ADD_SURVEY_GATE,
        )

    def broadcast(title: str, detail: str) -> WorkOption:
        return _link_option(
            key="broadcast",
            kind=WorkOptionKind.ALONGSIDE,
            label=title,
            why=detail,
            product="Workflows",
            does="Opens a new broadcast, named after this release and linked to it.",
            fields=[WorkFact(label="Release", value=release.name)],
            run_label="New broadcast",
            to=_broadcast_new_href(release),
            mcp_tools=["broadcasts-create"],
        )

    wants_survey = not has_surveys
    if stage == "flag":
        if not facts.experiments:
            options.append(experiment())
        if not facts.early_access:
            options.append(early_access())
        if wants_survey:
            options.append(survey("people who get the flag"))
    elif stage == "experiment":
        if wants_survey:
            options.append(survey("people in the test"))
    elif stage == "early_access":
        if not release.broadcasts:
            options.append(broadcast("Invite users to try it", "Announce the beta to the users who can opt in."))
        if wants_survey:
            options.append(survey("people who opted in"))
    elif stage == "released":
        if not release.broadcasts:
            options.append(broadcast("Tell users it's live", "Announce the release to everyone."))
        if wants_survey:
            options.append(survey("everyone who has it"))
    return options


def _survey_status(survey: LinkedSurveyDTO) -> str:
    if survey.archived:
        return "Archived"
    if survey.end_date:
        return "Complete"
    return "Running" if survey.start_date else "Draft"


def _survey_line(survey: LinkedSurveyDTO, now: datetime) -> WorkLine:
    facts = [WorkFact(label="Status", value=_survey_status(survey))]
    if survey.start_date:
        facts.append(WorkFact(label="Started", value=_day(survey.start_date, now)))
    if survey.end_date:
        facts.append(WorkFact(label="Ended", value=_day(survey.end_date, now)))
    key = f"survey:{survey.id}"
    return WorkLine(
        key=key,
        steps=[
            WorkStep(
                key=key,
                title=survey.name,
                description="A survey linked to this release.",
                area=AREA,
                item=WorkItem(
                    type="survey",
                    id=str(survey.id),
                    name=survey.name,
                    kind_label="survey",
                    product="Surveys",
                    href=f"/surveys/{survey.id}",
                ),
                facts=facts,
                options=[],
                alongside=[],
            )
        ],
    )


def _insight_line(insight: LinkedInsightDTO) -> WorkLine:
    key = f"insight:{insight.id}"
    return WorkLine(
        key=key,
        steps=[
            WorkStep(
                key=key,
                title=insight.name,
                description="An insight linked to this release.",
                area=AREA,
                item=WorkItem(
                    type="insight",
                    id=str(insight.id),
                    name=insight.name,
                    kind_label="insight",
                    product="Product analytics",
                    href=f"/insights/{insight.short_id}",
                ),
                facts=[WorkFact(label="Status", value="Deleted")] if insight.deleted else [],
                options=[],
                alongside=[],
            )
        ],
    )


def _broadcast_line(broadcast: LinkedBroadcastDTO) -> WorkLine:
    key = f"broadcast:{broadcast.id}"
    name = broadcast.name or "Untitled broadcast"
    return WorkLine(
        key=key,
        steps=[
            WorkStep(
                key=key,
                title=name,
                description="A broadcast linked to this release.",
                area=AREA,
                item=WorkItem(
                    type="broadcast",
                    id=str(broadcast.id),
                    name=name,
                    kind_label="broadcast",
                    product="Workflows",
                    href=f"/broadcasts/{broadcast.id}",
                ),
                facts=[WorkFact(label="Status", value=broadcast.status)],
                options=[],
                alongside=[],
            )
        ],
    )


@frozen
class _TestingStart:
    date: datetime
    item: WorkItem
    experiment: WorkExperiment | None
    early_access: WorkEarlyAccessFeature | None


def _testing_starts(facts: _Facts) -> list[_TestingStart]:
    starts = [
        _TestingStart(
            date=experiment.start_date, item=_experiment_item(experiment), experiment=experiment, early_access=None
        )
        for experiment in facts.experiments
        if experiment.start_date
    ] + [
        _TestingStart(date=feature.created_at, item=_early_access_item(feature), experiment=None, early_access=feature)
        for feature in facts.early_access
    ]
    return sorted(starts, key=lambda start: start.date)


def _rolled_out_label(facts: _Facts) -> str:
    if facts.ended:
        return "Clean up the flag"
    return "Roll out the winner" if facts.last_done else "Roll out to more users"


@frozen
class _StagePlan:
    key: LifecycleKey
    title: str
    item: WorkItem | None
    facts: list[WorkFact]
    done_description: str
    chosen_label: str | None = None


def _testing_plan(facts: _Facts, stage: Stage) -> _StagePlan:
    focus = (
        facts.current or next(iter(facts.paused), None) or next(iter(facts.drafts), None) or facts.last_done
        if stage == "experiment"
        else None
    )
    starts = _testing_starts(facts)
    first_start = starts[0] if starts else None
    if focus is None and first_start and first_start.experiment:
        focus = first_start.experiment
    if focus is None and (first_start is None or first_start.early_access is None) and facts.experiments:
        focus = facts.experiments[0]
    if focus is not None:
        launched = "Experiment launched" if focus.start_date else "Experiment drafted"
        return _StagePlan(
            key="testing",
            title="Experiment",
            item=_experiment_item(focus),
            facts=_experiment_fields(focus, facts),
            done_description=f"{launched}: {focus.name}",
            chosen_label=_rolled_out_label(facts),
        )
    feature = first_start.early_access if first_start else None
    if feature is None:
        return _StagePlan(
            key="testing",
            title="Testing",
            item=None,
            facts=[],
            done_description="Testing",
            chosen_label=_rolled_out_label(facts),
        )
    opened = _is_enrolling(feature) or feature.stage == "general-availability"
    return _StagePlan(
        key="testing",
        title="Early access",
        item=_early_access_item(feature),
        facts=_early_access_fields(feature),
        done_description=f"{'Early access opened' if opened else 'Early access created'}: {feature.name}",
        chosen_label=_rolled_out_label(facts),
    )


def _flag_plan(facts: _Facts, testing: _StagePlan | None) -> _StagePlan:
    flag = facts.flags[0] if facts.flags else None
    flag_facts: list[WorkFact] = []
    if flag:
        flag_facts.append(WorkFact(label="Flag", value=flag.key))
        if len(facts.flags) > 1:
            flag_facts.append(WorkFact(label="Flags", value=str(len(facts.flags))))
        if facts.audience_summary:
            flag_facts.append(WorkFact(label="Who gets it", value=facts.audience_summary))
        if facts.first_flag_created:
            flag_facts.append(WorkFact(label="Created", value=_day(facts.first_flag_created, facts.now)))
    if testing is None:
        chosen = _rolled_out_label(facts)
    elif testing.item and testing.item.type == "early_access_feature":
        chosen = "Let users opt in early"
    else:
        chosen = "Measure the impact"
    return _StagePlan(
        key="flag",
        title="Behind a flag",
        item=_flag_item(flag) if flag else None,
        facts=flag_facts,
        done_description=f"Flag {flag.key} created" if flag else "Behind flags you cannot see",
        chosen_label=chosen,
    )


def _stage_plans(facts: _Facts, stage: Stage) -> list[_StagePlan]:
    release = facts.release
    stage_index = _STAGE_INDEX[stage]
    planned_at = (
        facts.first_flag_created
        if facts.first_flag_created and facts.first_flag_created < release.created_at
        else release.created_at
    )
    plans = [
        _StagePlan(
            key="planned",
            title="Planned",
            item=_release_item(release),
            facts=[WorkFact(label="Created", value=_day(planned_at, facts.now))],
            done_description="Grouped into this release" if facts.flags else "Release created",
            chosen_label="Link a feature flag",
        )
    ]
    testing_happened = stage_index == 2 or (stage_index == 3 and bool(facts.experiments or facts.early_access))
    testing = _testing_plan(facts, stage) if testing_happened else None
    if stage_index >= 1:
        plans.append(_flag_plan(facts, testing))
    if testing:
        plans.append(testing)
    if stage_index == 3:
        flag = facts.flags[0] if facts.flags else None
        plans.append(
            _StagePlan(
                key="released",
                title="Ended" if facts.ended else "Rolled out",
                item=_flag_item(flag) if flag else None,
                facts=[
                    WorkFact(label="Who gets it", value="Nobody, the flags are archived" if facts.ended else "Everyone")
                ],
                done_description="Release ended" if facts.ended else "Rolled out to all users",
            )
        )
    return plans


def _step_key(release_id: UUID, plan: _StagePlan) -> str:
    base = f"release:{release_id}:{plan.key}"
    return f"{base}:{plan.item.type}:{plan.item.id}" if plan.item and plan.key != "planned" else base


def release_work_thread(work: ReleaseWorkFacts) -> WorkThread:
    facts = _facts(work)
    stage = _stage(facts)
    release = facts.release
    plans = _stage_plans(facts, stage)
    copy = _copy(facts)
    next_step = _release_next_step(facts)
    alongside = [
        *(_survey_line(survey, facts.now) for survey in release.surveys),
        *(_insight_line(insight) for insight in release.insights),
        *(_broadcast_line(broadcast) for broadcast in release.broadcasts),
    ]
    steps: list[WorkStep] = []
    for index, plan in enumerate(plans):
        last = index == len(plans) - 1
        if not last:
            steps.append(
                WorkStep(
                    key=_step_key(release.id, plan),
                    title=plan.title,
                    description=plan.done_description,
                    area=AREA,
                    item=plan.item,
                    facts=plan.facts,
                    options=[],
                    alongside=[],
                    chosen_label=plan.chosen_label,
                )
            )
            continue
        options = _next_options(next_step, facts) if next_step else []
        steps.append(
            WorkStep(
                key=_step_key(release.id, plan),
                title=plan.title,
                description=f"{copy.headline}. {copy.detail}" if copy.detail else copy.headline,
                area=AREA,
                item=plan.item,
                facts=plan.facts,
                options=[*options, *_alongside_options(facts, stage)],
                alongside=alongside,
            )
        )
    return WorkThread(
        key=f"release:{release.id}",
        name=release.name,
        line=WorkLine(key=f"release:{release.id}", steps=steps),
    )


def is_in_flight(work: ReleaseWorkFacts) -> bool:
    return _stage(_facts(work)) != "ended"
