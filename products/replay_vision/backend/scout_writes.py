"""Rules a Signals scout's scanner writes must clear, on top of the scopes its token carries.

A person grants one scout `replay_scanner:write` from the scout's settings, and that grant is
deliberately narrower than the scope object: it excludes deletion, and it holds a scout to a credit
limit on any scanner it puts to work. Neither can be expressed in the token, because one scope
object covers the whole scanner surface, so both are enforced here.

Every rule applies to scout sandbox callers alone (`is_scout_sandbox_request`), so a person working
in the app or a personal API key sees no change.
"""

from collections.abc import Mapping
from typing import Any

from rest_framework.exceptions import PermissionDenied, ValidationError

from products.replay_vision.backend.models.replay_scanner import ReplayScanner

DELETE_REFUSED = "Scouts cannot delete scanners. Set `enabled: false` to stop this one."

CREDIT_LIMIT_REQUIRED = (
    "Set a credit limit on a scanner you create. A scanner spends credits on every session it "
    "observes, so without one it can use up the organization's whole Replay vision budget. "
    "`vision-scanners-estimate-create` projects what a scanner will spend per month."
)

CREDIT_LIMIT_NOT_CLEARABLE = (
    "Scouts cannot remove a scanner's credit limit. Raise the limit instead, or set "
    "`enabled: false` to stop the scanner."
)

CREDIT_LIMIT_REQUIRED_TO_ENABLE = (
    "Set a credit limit before you enable this scanner. It has none, and an enabled scanner with "
    "no limit can use up the organization's whole Replay vision budget."
)


def refuse_scout_scanner_scan(is_scout_caller: bool) -> None:
    if is_scout_caller:
        raise PermissionDenied("Scouts cannot start manual scans. Create or enable a scanner with a credit limit.")


def refuse_scout_scanner_delete(is_scout_caller: bool) -> None:
    """Refuse a scout's delete.

    Deleting a scanner is permanent and takes its past observations with it, so it fails the
    recoverable bar the other per-scout grants meet. Disabling covers the job the grant exists
    for: a scanner a scout stops keeps its history and a person can turn it back on.
    """
    if is_scout_caller:
        raise PermissionDenied(DELETE_REFUSED)


def _check_credit_ceiling(credit_limit: int, max_credit_limit: int | None) -> None:
    if max_credit_limit is None:
        raise ValidationError(
            {
                "credit_limit": "Set a finite organization Replay vision credit quota before a scout increases scanner spend."
            }
        )
    if credit_limit > max_credit_limit:
        raise ValidationError(
            {
                "credit_limit": "A scout's scanner credit limit cannot exceed the organization's Replay vision credit quota."
            }
        )


def check_scout_scanner_credit_limit(
    is_scout_caller: bool,
    *,
    instance: ReplayScanner | None,
    attrs: Mapping[str, Any],
    max_credit_limit: int | None = None,
) -> None:
    """Refuse a scout write that would leave a scanner able to scan with no cap on its spend.

    An enabled scanner sweeps matching recordings every few minutes and spends credits on each
    observation, and neither creating nor enabling one checks the organization's quota. A broad
    query can therefore exhaust a budget on the first sweeps. Wording in the run prompt is not a
    bound on that, so the rule is a required field: the scout sets the ceiling before the spend
    starts, and cannot take it away afterwards.

    A scout may fix the prompt or disable a scanner without a limit. Changes to targeting,
    sampling, or the model require a limit because they can increase its spend.
    """
    if not is_scout_caller:
        return
    if instance is None:
        if attrs.get("credit_limit") is None:
            raise ValidationError({"credit_limit": CREDIT_LIMIT_REQUIRED})
        _check_credit_ceiling(attrs["credit_limit"], max_credit_limit)
        return
    if "credit_limit" in attrs and attrs["credit_limit"] is None:
        raise ValidationError({"credit_limit": CREDIT_LIMIT_NOT_CLEARABLE})
    turning_on = attrs.get("enabled") and not instance.enabled
    cost_fields = {"query", "sampling_rate", "sampling_mode", "provider", "model", "experiment_targeting"}
    changes_cost = any(field in attrs and attrs[field] != getattr(instance, field) for field in cost_fields)
    changes_enabled_cost = attrs.get("enabled", instance.enabled) and changes_cost
    credit_limit = attrs.get("credit_limit", instance.credit_limit)
    if credit_limit is None:
        if turning_on:
            raise ValidationError({"credit_limit": CREDIT_LIMIT_REQUIRED_TO_ENABLE})
        if changes_enabled_cost:
            raise ValidationError(
                {
                    "credit_limit": "Set a credit limit before you change the targeting, sampling, or model of an enabled scanner."
                }
            )
        return
    raises_limit = "credit_limit" in attrs and (instance.credit_limit is None or credit_limit > instance.credit_limit)
    if turning_on or changes_enabled_cost or raises_limit:
        _check_credit_ceiling(credit_limit, max_credit_limit)
