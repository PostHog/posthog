"""Copies of the enterprise definition fields on the base tables.

The enterprise fields move from `ee_enterpriseeventdefinition` and `ee_enterprisepropertydefinition`
onto `posthog_eventdefinition` and `posthog_propertydefinition`, into columns with the same names.
Until reads move over, the enterprise models write each value to both tables, and nothing reads the
copies. Django does not track the base-table columns yet: a model with two fields on one column name
breaks `.raw()` on Django 6, and the definition list endpoints build their rows with `.raw()`.
"""

from collections.abc import Iterable, Sequence

from django.db import connections, models, router

EVENT_DEFINITION_COPIED_FIELDS: Sequence[str] = (
    "description",
    "owner",
    "updated_at",
    "updated_by",
    "verified",
    "verified_at",
    "verified_by",
    "hidden",
    "default_columns",
)

PROPERTY_DEFINITION_COPIED_FIELDS: Sequence[str] = (
    "description",
    "updated_at",
    "updated_by",
    "verified",
    "verified_at",
    "verified_by",
    "hidden",
)


def _concrete_field(instance: models.Model, name: str) -> models.Field:
    field = instance._meta.get_field(name)
    if not isinstance(field, models.Field):
        raise TypeError(f"{instance._meta.label}.{name} is not a concrete field")
    return field


def copy_enterprise_fields(
    instance: models.Model,
    base_model: type[models.Model],
    field_names: Sequence[str],
    update_fields: Iterable[str] | None,
) -> None:
    """Write the saved enterprise values to the same-named columns of the base table.

    Call it after the enterprise save, in the same transaction, so `updated_at` holds the value that
    auto_now wrote. A partial save copies only the fields it saved.
    """
    fields = [_concrete_field(instance, name) for name in field_names]
    if update_fields is not None:
        requested = set(update_fields)
        fields = [field for field in fields if field.name in requested or field.attname in requested]
    if not fields:
        return

    using = router.db_for_write(base_model, instance=instance)
    connection = connections[using]
    quote = connection.ops.quote_name
    # Trusted identifiers: the table and column names come from Django model metadata.
    assignments = ", ".join(f"{quote(field.column)} = %s" for field in fields)
    query = (
        f"UPDATE {quote(base_model._meta.db_table)} SET {assignments} WHERE {quote(base_model._meta.pk.column)} = %s"
    )
    values = [field.get_db_prep_save(getattr(instance, field.attname), connection) for field in fields]
    with connection.cursor() as cursor:
        cursor.execute(query, [*values, instance.pk])
