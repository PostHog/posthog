from typing import TYPE_CHECKING

from rest_framework import serializers

if TYPE_CHECKING:
    from products.feature_flags.backend.models.feature_flag import FeatureFlag

FLAG_OWNER_EXPERIMENT = "experiment"
FLAG_OWNER_SURVEY = "survey"
FLAG_OWNER_PRODUCT_TOUR = "product_tour"
FLAG_OWNER_EARLY_ACCESS = "early_access_feature"

_OWNER_LABELS = {
    FLAG_OWNER_EXPERIMENT: "an experiment",
    FLAG_OWNER_SURVEY: "a survey",
    FLAG_OWNER_PRODUCT_TOUR: "a product tour",
    FLAG_OWNER_EARLY_ACCESS: "an early access feature",
}

# Reverse accessors keep this free of cross-product imports.
#
# `linked_flag` is absent on purpose: a survey or product tour may point at another product's flag
# to target its audience, which references the flag without owning it.
_OWNING_ACCESSORS: tuple[tuple[str, str], ...] = (
    ("experiment_set", FLAG_OWNER_EXPERIMENT),
    ("surveys_targeting_flag", FLAG_OWNER_SURVEY),
    ("surveys_internal_targeting_flag", FLAG_OWNER_SURVEY),
    ("surveys_internal_response_sampling_flag", FLAG_OWNER_SURVEY),
    ("product_tours_internal_targeting_flag", FLAG_OWNER_PRODUCT_TOUR),
    ("features", FLAG_OWNER_EARLY_ACCESS),
)


def flag_owner_kind(flag: "FeatureFlag") -> str | None:
    """Return the product that owns this flag, or None when nothing owns it.

    Ownership decides which approval policy family governs a write, so a flag must have at most one
    owner. Production already satisfies that: of the owned flags in US, all but three have exactly
    one owner. `assert_flag_unowned` keeps it that way.
    """
    for accessor, kind in _OWNING_ACCESSORS:
        if getattr(flag, accessor).exists():
            return kind
    return None


def assert_flag_available_for(flag: "FeatureFlag", *, product: str) -> None:
    """Reject adopting a flag that a different product already owns.

    Ownership decides which approval policy family governs a write, so what must stay unambiguous
    is the owning *product*, not the owning object. Two experiments sharing one flag still resolve
    to one family, so this permits it; a product that wants one object per flag enforces that
    itself, as early access features do.

    Call this only when a write points a product at a flag it did not point at before. Re-saving a
    parent that already owns the flag must not raise, so the caller compares the incoming id
    against the stored one first.
    """
    owner = flag_owner_kind(flag)
    if owner is not None and owner != product:
        raise serializers.ValidationError(
            f"The feature flag {flag.key} already belongs to {_OWNER_LABELS[owner]}. "
            f"A flag can belong to one thing at a time. Pick a different flag, "
            f"or edit this one where it is already used."
        )
