"""The approval gate: what a hog may do outside PostHog, and who said so."""

from __future__ import annotations

from uuid import UUID

from django.db.models import Count
from django.utils import timezone

from ..facade.enums import HogActionDecision, HogActionStatus, HogMessageAuthor, HogRuleEffect, HogStatus, HogWakeCause
from ..models import Hog, HogAction, HogRule
from . import (
    hogs as hogs_logic,
    runner,
)


class ApprovalError(ValueError):
    pass


def _effect_for(hog: Hog, kind: str) -> HogRuleEffect:
    """No rule means ask."""
    rule = HogRule.objects.filter(hog=hog, kind=kind).first()
    return HogRuleEffect(rule.effect) if rule else HogRuleEffect.ASK


def _set_rule(hog: Hog, kind: str, effect: HogRuleEffect) -> None:
    HogRule.objects.update_or_create(hog=hog, kind=kind, defaults={"team_id": hog.team_id, "effect": effect.value})


def propose_action(hog: Hog, *, kind: str, label: str, draft: str) -> HogAction:
    """Decide the action against the owner's rule for its kind. Without a rule it waits for the owner."""
    hogs_logic.mark_seen(hog)
    effect = _effect_for(hog, kind)
    status = {
        HogRuleEffect.ALLOW: HogActionStatus.APPROVED,
        HogRuleEffect.DENY: HogActionStatus.DENIED,
        HogRuleEffect.ASK: HogActionStatus.PENDING,
    }[effect]
    action = HogAction.objects.create(
        team_id=hog.team_id,
        hog=hog,
        kind=kind,
        label=label,
        draft=draft,
        status=status.value,
        decided_at=None if status == HogActionStatus.PENDING else timezone.now(),
        task_run_id=hog.current_run_id,
    )
    if status == HogActionStatus.PENDING:
        hogs_logic.add_message(
            hog,
            author=HogMessageAuthor.HOG,
            content=f"Needs your approval: {label}",
            task_run_id=hog.current_run_id,
            action=action,
        )
    return action


def list_actions(
    *, team_id: int, user_id: int, hog_id: UUID | None = None, status: HogActionStatus | None = None
) -> list[HogAction]:
    actions = HogAction.objects.filter(team_id=team_id, hog__created_by_id=user_id, hog__deleted=False).select_related(
        "hog"
    )
    if hog_id is not None:
        actions = actions.filter(hog_id=hog_id)
    if status is not None:
        actions = actions.filter(status=status.value)
    return list(actions.order_by("-created_at")[:200])


def list_rules(hog: Hog) -> list[HogRule]:
    return list(hog.rules.order_by("kind"))


def set_rule(hog: Hog, *, kind: str, effect: HogRuleEffect) -> HogRule:
    _set_rule(hog, kind, effect)
    return HogRule.objects.get(hog=hog, kind=kind)


def decide_action(
    hog: Hog, action_id: UUID, *, decision: HogActionDecision, always: bool, draft: str | None
) -> HogAction | None:
    """The owner's answer. Raises ApprovalError when the action is no longer waiting."""
    action = HogAction.objects.filter(hog=hog, id=action_id).select_related("hog").first()
    if action is None:
        return None
    if action.status != HogActionStatus.PENDING:
        raise ApprovalError(f"This action is already {action.status}.")
    approved = decision == HogActionDecision.APPROVE
    if approved and draft is not None:
        action.draft = draft
    action.status = (HogActionStatus.APPROVED if approved else HogActionStatus.DENIED).value
    action.decided_at = timezone.now()
    action.save(update_fields=["draft", "status", "decided_at", "updated_at"])
    if always:
        _set_rule(hog, action.kind, HogRuleEffect.ALLOW if approved else HogRuleEffect.DENY)
    if not approved:
        hogs_logic.add_message(
            hog,
            author=HogMessageAuthor.SYSTEM,
            content=f'Your owner denied the action "{action.label}" ({action.kind}). Do not do it.',
            in_chat=False,
        )
        return action
    if hog.status != HogStatus.PAUSED:
        runner.wake_hog(
            hog,
            trigger=(
                f"Your owner approved an action you proposed. Do exactly this now, and nothing more:\n\n"
                f"Action ID: {action.id}\nKind: {action.kind}\nWhat: {action.label}\n\n"
                f"The approved text, which your owner may have edited:\n{action.draft or '(none)'}\n\n"
                "Then call hog-action-done with the action ID and what happened."
            ),
            cause=HogWakeCause.APPROVAL,
        )
    return action


def complete_action(hog: Hog, action_id: UUID, *, result: str) -> HogAction | None:
    """The hog's record that it carried out an approved action. Raises ApprovalError for any other action."""
    hogs_logic.mark_seen(hog)
    action = HogAction.objects.filter(hog=hog, id=action_id).select_related("hog").first()
    if action is None:
        return None
    if action.status != HogActionStatus.APPROVED:
        raise ApprovalError(f"Only an approved action can be completed. This one is {action.status}.")
    action.status = HogActionStatus.DONE.value
    action.result = result
    action.save(update_fields=["status", "result", "updated_at"])
    return action


def pending_action_counts(hog_ids: list[UUID]) -> dict[UUID, int]:
    rows = (
        HogAction.objects.filter(hog_id__in=hog_ids, status=HogActionStatus.PENDING.value)
        .values("hog_id")
        .annotate(waiting=Count("id"))
    )
    return {row["hog_id"]: row["waiting"] for row in rows}
