from typing import TYPE_CHECKING, Optional, cast

from django.db.models import Case, CharField, Count, Exists, Model, OuterRef, QuerySet, Value, When
from django.db.models.fields.reverse_related import ForeignObjectRel

from rest_framework import serializers

from products.feature_flags.backend.facade.config import detect_config_format

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


# Relations onto FeatureFlag that deliberately do not confer ownership. Listed rather than
# inferred, so "standalone" is a classification somebody made instead of whatever was left over.
# `test_flag_ownership_relations_are_classified` fails when a relation appears in neither list,
# which is what stops a new owning product being read as standalone because nobody registered it.
_REFERENCE_ACCESSORS: frozenset[str] = frozenset(
    {
        # A survey or tour may point at another product's flag to target its audience.
        "surveys_linked_flag",
        "product_tours_linked_flag",
        # Evaluation and override bookkeeping, not a product that owns the flag.
        "flag_evaluation_contexts",
        "featureflagoverride_set",
        "featureflagdashboards_set",
        "access",
    }
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

    A flag stored in another config format is not available either: every adopting product reads
    and writes its document as config version 1.
    """
    if detect_config_format(flag.filters).kind != "v1":
        raise serializers.ValidationError(
            f"The feature flag {flag.key} uses a configuration format that {_OWNER_LABELS[product]} "
            "cannot use yet. Pick a different flag."
        )
    owner = flag_owner_kind(flag)
    if owner is not None and owner != product:
        raise serializers.ValidationError(
            f"The feature flag {flag.key} already belongs to {_OWNER_LABELS[owner]}. "
            f"Pick a different flag, or edit this one where it is already used."
        )


def _owning_conditions(model: type[Model]) -> list[tuple[str, Exists]]:
    """One EXISTS per owning relation, in the order `flag_owner_kind` checks them.

    Built from `_OWNING_ACCESSORS` rather than written out, so a relation cannot be classified in
    one place and missed in the other. The manager matters for the same reason it does there: an
    archived product tour still holds its flag.
    """
    relations = {
        relation.get_accessor_name(): relation
        for relation in model._meta.get_fields()
        if isinstance(relation, ForeignObjectRel)
    }
    conditions = []
    for accessor, kind, manager in _OWNING_ACCESSORS:
        relation = relations[accessor]
        # Every accessor in `_OWNING_ACCESSORS` names a concrete reverse relation, so the related
        # model is a model class rather than the "self" sentinel the field type allows.
        related_model = cast(type[Model], relation.related_model)
        objects = getattr(related_model, manager) if manager else related_model._default_manager
        conditions.append((kind, Exists(objects.filter(**{relation.field.name: OuterRef("pk")}))))
    return conditions


def owner_kind_counts(flags: "QuerySet[FeatureFlag]") -> dict[Optional[str], int]:
    """Count the flags in a queryset by the product that owns each one.

    The same classification and the same precedence as `flag_owner_kind`, as one query, because
    the populations worth counting are too large to classify row by row. A flag no product owns
    counts under None, exactly as that function reports it.
    """
    whens = [When(condition, then=Value(kind)) for kind, condition in _owning_conditions(flags.model)]
    rows = (
        flags.annotate(owner_kind=Case(*whens, default=Value(None, output_field=CharField())))
        .values("owner_kind")
        .annotate(total=Count("id"))
    )
    return {row["owner_kind"]: row["total"] for row in rows}
