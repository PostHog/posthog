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

# `linked_flag` is absent on purpose: a survey or product tour may point at another product's flag
# to target its audience, which references the flag without owning it.
#
# The third element names the manager to read the relation through, or None for the default one.
# Django builds a reverse accessor from the related model's default manager, and
# `ProductTour.objects` hides archived tours. An archived tour keeps its `internal_targeting_flag`,
# so the default manager would report that flag as free while a tour still holds it, and
# unarchiving the tour would then produce the second owner this module exists to prevent.
_OWNING_ACCESSORS: tuple[tuple[str, str, str | None], ...] = (
    ("experiment_set", FLAG_OWNER_EXPERIMENT, None),
    ("surveys_targeting_flag", FLAG_OWNER_SURVEY, None),
    ("surveys_internal_targeting_flag", FLAG_OWNER_SURVEY, None),
    ("surveys_internal_response_sampling_flag", FLAG_OWNER_SURVEY, None),
    ("product_tours_internal_targeting_flag", FLAG_OWNER_PRODUCT_TOUR, "all_objects"),
    ("features", FLAG_OWNER_EARLY_ACCESS, None),
)


def flag_owner_kind(flag: "FeatureFlag") -> str | None:
    """Return the product that owns this flag, or None when nothing owns it.

    A flag may be owned by at most one product. `assert_flag_available_for` keeps it that way.
    """
    for accessor, kind, manager in _OWNING_ACCESSORS:
        related = getattr(flag, accessor)
        if manager is not None:
            related = related(manager=manager)
        if related.exists():
            return kind
    return None


def assert_flag_available_for(flag: "FeatureFlag", *, product: str) -> None:
    """Reject adopting a flag that a different product already owns.

    What must stay unambiguous is the owning *product*, not the owning object. Two experiments
    sharing one flag leave one owner, so this permits it; a product that wants one object per flag
    enforces that itself, as early access features do.

    Call this only when a write points a product at a flag it did not point at before. Re-saving a
    parent that already owns the flag must not raise, so the caller compares the incoming id
    against the stored one first.

    This reads before the caller writes, so two products adopting the same free flag at the same
    moment can both pass. No database constraint can span the four owning tables, so the remaining
    window is accepted rather than locked.
    """
    owner = flag_owner_kind(flag)
    if owner is not None and owner != product:
        raise serializers.ValidationError(
            f"The feature flag {flag.key} already belongs to {_OWNER_LABELS[owner]}. "
            f"Pick a different flag, or edit this one where it is already used."
        )
