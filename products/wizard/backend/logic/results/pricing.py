from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.wizard.backend.facade.contracts import WizardSpendRange
from products.wizard.backend.logic.results.parser import SavingClaim


class UnpriceableBillingError(ValueError):
    pass


@frozen
class _Tier:
    unit_amount_usd: float
    flat_amount_usd: float
    up_to: float | None


@frozen
class _PricedUsage:
    tiers: tuple[tuple[_Tier, ...], ...]
    usage: float


@frozen
class PricedClaim:
    claim: SavingClaim
    saving_monthly: WizardSpendRange


@frozen
class PricedSavings:
    baseline_monthly: float
    saving_monthly: WizardSpendRange
    claims: tuple[PricedClaim, ...]


def price_usage(usage: float, tiers: Sequence[Sequence[_Tier]], discount_percent: float = 0) -> float:
    """Graduated pricing, matching `convertUsageToAmount` in `frontend/src/scenes/billing/billing-utils.ts`.

    Add-on tiers line up with the product's tiers by index, so their unit and flat amounts add to the product's.
    """
    if not tiers:
        return 0.0

    combined = [
        _Tier(
            unit_amount_usd=sum(addon_or_product[index].unit_amount_usd for addon_or_product in tiers),
            flat_amount_usd=sum(addon_or_product[index].flat_amount_usd for addon_or_product in tiers),
            up_to=tier.up_to,
        )
        for index, tier in enumerate(tiers[0])
    ]

    remaining = usage
    amount = 0.0
    previous_up_to = 0.0
    for tier in combined:
        if remaining <= 0:
            break
        tier_size = tier.up_to - previous_up_to if tier.up_to is not None else float("inf")
        used = min(remaining, tier_size)
        remaining -= used
        amount += tier.unit_amount_usd * used + tier.flat_amount_usd
        previous_up_to = tier.up_to or previous_up_to

    if discount_percent:
        amount *= 1 - discount_percent / 100
    return amount


def price_savings(billing: Mapping[str, Any], claims: Sequence[SavingClaim]) -> PricedSavings:
    """Prices each claim at the margin of the organization's projected usage.

    Removed volume comes off the top of the usage, so it is billed at the highest tier reached, which is the
    cheapest per unit. A product's total uses the claims' combined removal, so it is not the sum of the claims.
    """
    discount_percent = float(billing.get("discount_percent") or 0)
    usages = {claim.billing_type: _priced_usage(billing, claim.billing_type) for claim in claims}

    priced = tuple(
        PricedClaim(
            claim=claim,
            saving_monthly=_saving(usages[claim.billing_type], claim.volume_removed, discount_percent),
        )
        for claim in claims
    )

    removed_by_type: dict[str, list[WizardSpendRange]] = defaultdict(list)
    for claim in claims:
        removed_by_type[claim.billing_type].append(claim.volume_removed)

    totals = [
        _saving(
            usages[billing_type],
            WizardSpendRange(low=sum(r.low for r in removed), high=sum(r.high for r in removed)),
            discount_percent,
        )
        for billing_type, removed in removed_by_type.items()
    ]

    return PricedSavings(
        baseline_monthly=_baseline(billing),
        saving_monthly=WizardSpendRange(low=sum(t.low for t in totals), high=sum(t.high for t in totals)),
        claims=priced,
    )


def _saving(usage: _PricedUsage, removed: WizardSpendRange, discount_percent: float) -> WizardSpendRange:
    before = price_usage(usage.usage, usage.tiers, discount_percent)

    def saved(volume: float) -> float:
        return round(before - price_usage(max(usage.usage - volume, 0), usage.tiers, discount_percent), 2)

    return WizardSpendRange(low=saved(removed.low), high=saved(removed.high))


def _priced_usage(billing: Mapping[str, Any], billing_type: str) -> _PricedUsage:
    for product in billing.get("products") or []:
        if product.get("type") == billing_type:
            # Subscribed add-ons that bill on the product's own usage add their tiers to it.
            same_usage_addons = [
                addon
                for addon in product.get("addons") or []
                if addon.get("subscribed")
                and addon.get("tiers")
                and addon.get("usage_key") in (None, product.get("usage_key"))
                and len(addon["tiers"]) == len(product.get("tiers") or [])
            ]
            return _usage_of(product, [product, *same_usage_addons])

        for addon in product.get("addons") or []:
            if addon.get("type") == billing_type and addon.get("subscribed"):
                return _usage_of(addon, [addon])

    raise UnpriceableBillingError(f"No billed product or add-on named {billing_type}")


def _usage_of(item: Mapping[str, Any], tiered: Sequence[Mapping[str, Any]]) -> _PricedUsage:
    if not item.get("tiers"):
        raise UnpriceableBillingError("The product has no usage tiers")
    usage = item.get("projected_usage")
    if usage is None:
        usage = item.get("current_usage")
    if not isinstance(usage, int | float) or isinstance(usage, bool):
        raise UnpriceableBillingError("The product has no usage")
    return _PricedUsage(tiers=tuple(_tiers(entry["tiers"]) for entry in tiered), usage=float(usage))


def _tiers(raw: Sequence[Mapping[str, Any]]) -> tuple[_Tier, ...]:
    try:
        return tuple(
            _Tier(
                unit_amount_usd=float(tier.get("unit_amount_usd") or 0),
                flat_amount_usd=float(tier.get("flat_amount_usd") or 0),
                up_to=float(tier["up_to"]) if tier.get("up_to") is not None else None,
            )
            for tier in raw
        )
    except (TypeError, ValueError) as error:
        raise UnpriceableBillingError("Invalid tier") from error


def _baseline(billing: Mapping[str, Any]) -> float:
    for key in ("projected_total_amount_usd_after_discount", "projected_total_amount_usd"):
        value = billing.get(key)
        if value not in (None, ""):
            try:
                return round(float(value), 2)
            except (TypeError, ValueError):
                break
    raise UnpriceableBillingError("The billing response has no projected total")
