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


def _column(model: type[models.Model], name: str) -> str:
    field = model._meta.get_field(name)
    if not isinstance(field, models.Field) or field.column is None:
        raise TypeError(f"{model._meta.label}.{name} is not a concrete field")
    return field.column


def _pk_column(model: type[models.Model]) -> str:
    pk = model._meta.pk
    if pk is None or pk.column is None:
        raise TypeError(f"{model._meta.label} has no primary key column")
    return pk.column


def lock_base_row(instance: models.Model, base_model: type[models.Model]) -> None:
    """Lock the base row first, the order a save that writes both tables takes, so that a partial
    save that writes only the enterprise row cannot deadlock against it. Call it in the transaction."""
    list(base_model._base_manager.select_for_update().filter(pk=instance.pk).values_list("pk", flat=True))


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
    model = type(instance)
    fields = [model._meta.get_field(name) for name in field_names]
    concrete = [field for field in fields if isinstance(field, models.Field)]
    if update_fields is not None:
        requested = set(update_fields)
        concrete = [field for field in concrete if field.name in requested or field.attname in requested]
    if not concrete:
        return

    connection = connections[router.db_for_write(base_model, instance=instance)]
    quote = connection.ops.quote_name
    # Trusted identifiers: the table and column names come from Django model metadata.
    assignments = ", ".join(f"{quote(_column(model, field.name))} = %s" for field in concrete)
    query = f"UPDATE {quote(base_model._meta.db_table)} SET {assignments} WHERE {quote(_pk_column(base_model))} = %s"
    values = [field.get_db_prep_save(getattr(instance, field.attname), connection) for field in concrete]
    with connection.cursor() as cursor:
        cursor.execute(query, [*values, instance.pk])


def clear_copied_user_ids(
    enterprise_model: type[models.Model], base_model: type[models.Model], field_names: Sequence[str], user_id: int
) -> None:
    """Clear the base-table copies of a user reference before the user is deleted.

    The delete sets the enterprise user columns to NULL with bulk updates, which skip save(). The
    enterprise rows find the affected base rows through their indexed user columns, so the large base
    tables are not scanned.
    """
    connection = connections[router.db_for_write(base_model)]
    quote = connection.ops.quote_name
    # Trusted identifiers: the table and column names come from Django model metadata.
    base_table = quote(base_model._meta.db_table)
    enterprise_table = quote(enterprise_model._meta.db_table)
    join = f"enterprise.{quote(_pk_column(enterprise_model))} = base.{quote(_pk_column(base_model))}"
    with connection.cursor() as cursor:
        for name in field_names:
            column = quote(_column(enterprise_model, name))
            cursor.execute(
                f"UPDATE {base_table} AS base SET {column} = NULL FROM {enterprise_table} AS enterprise "
                f"WHERE {join} AND enterprise.{column} = %s",
                [user_id],
            )
