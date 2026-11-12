from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, TypeVar

from django.core.exceptions import ValidationError
from django.db import models, router, transaction

from pydantic import JsonValue

from posthog.dataclasses import frozen
from posthog.models.utils import UUIDModel

from products.signals.backend.filter_catalog_schema import CatalogBundle, validate_catalog_bundle
from products.signals.backend.filter_expression import FilterExpression, FilterValidationError

if TYPE_CHECKING:
    from django.db.models.base import ModelBase

CatalogModel = TypeVar("CatalogModel", bound=models.Model)


class CatalogQuerySet(models.QuerySet[CatalogModel]):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Catalog records must be written with save()")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Catalog history must be retained")

    def bulk_create(
        self,
        objs: Iterable[CatalogModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[CatalogModel]:
        raise ValidationError("Catalog records must be written with save()")


class InternalCatalogModel(UUIDModel):
    """Instance-global backend metadata; never stores tenant observations or values."""

    objects = CatalogQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, using: str | None = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        raise ValidationError("Catalog history must be retained")


@frozen
class CatalogPublication:
    source_created: bool
    version: int
    version_created: bool


def _validate_executable(bundle: dict[str, JsonValue]) -> None:
    catalog = CatalogBundle.model_validate(bundle)
    field_types = {field.name: field.type for field in catalog.fields}
    try:
        FilterExpression("", field_types)
        for starter in catalog.starter_expressions:
            FilterExpression(starter, field_types)
    except FilterValidationError as error:
        raise ValidationError("Catalog cannot be filtered: %(reason)s", params={"reason": str(error)}) from error


class SignalFilterSourceDefinition(InternalCatalogModel):
    class AdapterKind(models.TextChoices):
        WAREHOUSE = "warehouse"

    class RolloutState(models.TextChoices):
        DISABLED = "disabled"
        INTERNAL = "internal"
        ENABLED = "enabled"

    source_product = models.CharField(max_length=128)
    source_type = models.CharField(max_length=128)
    adapter_kind = models.CharField(max_length=32, choices=AdapterKind.choices)
    rollout_state = models.CharField(max_length=16, choices=RolloutState.choices, default=RolloutState.DISABLED)
    filter_query_eligible = models.BooleanField(default=False)
    active_catalog_version = models.ForeignKey(
        "signals.SignalFilterCatalogVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "signals"
        base_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(fields=["source_product", "source_type"], name="signals_filter_source_unique"),
            models.CheckConstraint(
                condition=models.Q(filter_query_eligible=False) | models.Q(active_catalog_version__isnull=False),
                name="signals_filter_eligible_catalog",
            ),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        using = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            original = (
                type(self).objects.using(using).select_for_update().filter(pk=self.pk).first() if self.pk else None
            )
            if original is not None:
                if (self.source_product, self.source_type, self.adapter_kind) != (
                    original.source_product,
                    original.source_type,
                    original.adapter_kind,
                ):
                    raise ValidationError("Source identity and adapter are immutable")
            if self.active_catalog_version_id is not None:
                if (
                    not SignalFilterCatalogVersion.objects.using(using)
                    .filter(pk=self.active_catalog_version_id, source_id=self.pk)
                    .exists()
                ):
                    raise ValidationError("Active catalog version must belong to this source")
            if self.filter_query_eligible and self.active_catalog_version_id is None:
                raise ValidationError("Filter eligibility requires an active catalog version")
            self.full_clean()
            super().save(force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields)

    def activate(self, catalog_version: SignalFilterCatalogVersion) -> None:
        if catalog_version.pk is None or catalog_version._state.adding:
            raise ValidationError("Catalog version must be saved before activation")
        self.active_catalog_version_id = catalog_version.pk
        self.save(update_fields=["active_catalog_version"])

    @classmethod
    def publish(
        cls,
        *,
        source_product: str,
        source_type: str,
        adapter_kind: SignalFilterSourceDefinition.AdapterKind,
        initial_rollout_state: SignalFilterSourceDefinition.RolloutState,
        bundle: dict[str, JsonValue],
    ) -> CatalogPublication:
        # Rollout state applies only to a new source, and eligibility is never set here,
        # so that a rerun cannot undo a rollout decision made after the first publish.
        validate_catalog_bundle(bundle)
        _validate_executable(bundle)
        using = router.db_for_write(cls)
        with transaction.atomic(using=using):
            source = (
                cls.objects.using(using)
                .select_for_update()
                .filter(source_product=source_product, source_type=source_type)
                .first()
            )
            source_created = source is None
            if source is None:
                source = cls(
                    source_product=source_product,
                    source_type=source_type,
                    adapter_kind=adapter_kind,
                    rollout_state=initial_rollout_state,
                )
                source.save(using=using)
            elif source.adapter_kind != adapter_kind:
                raise ValidationError("Source identity and adapter are immutable")
            active = source.active_catalog_version
            if active is not None and active.bundle == bundle:
                return CatalogPublication(source_created=False, version=active.version, version_created=False)
            latest = source.catalog_versions.aggregate(latest=models.Max("version"))["latest"] or 0
            catalog_version = SignalFilterCatalogVersion(source=source, version=latest + 1, bundle=bundle)
            catalog_version.save(using=using)
            source.activate(catalog_version)
        return CatalogPublication(source_created=source_created, version=catalog_version.version, version_created=True)


class SignalFilterCatalogVersion(InternalCatalogModel):
    source = models.ForeignKey(SignalFilterSourceDefinition, on_delete=models.PROTECT, related_name="catalog_versions")
    version = models.PositiveIntegerField()
    bundle = models.JSONField(validators=[validate_catalog_bundle])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "signals"
        base_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(fields=["source", "version"], name="signals_filter_catalog_version_unique"),
            models.CheckConstraint(condition=models.Q(version__gt=0), name="signals_filter_catalog_version_positive"),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if not self._state.adding or force_update or update_fields is not None:
            raise ValidationError("Catalog versions are immutable; create a new version")
        self.full_clean()
        super().save(force_insert=True, using=using)
