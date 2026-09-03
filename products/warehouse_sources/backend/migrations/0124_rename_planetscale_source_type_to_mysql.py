from django.db import migrations

# "PlanetScale" covered only the MySQL (Vitess) product. Now that PlanetScale Postgres has its
# own source type, the old value is renamed so the two read symmetrically.
_OLD_SOURCE_TYPE = "PlanetScale"
_NEW_SOURCE_TYPE = "PlanetScaleMySQL"

_SOURCE_TYPE_MODELS = ("ExternalDataSource", "PendingSourceCredential")


def _rename_source_type(apps, schema_editor, *, old: str, new: str) -> None:
    for model_name in _SOURCE_TYPE_MODELS:
        model = apps.get_model("warehouse_sources", model_name)
        schema_editor.execute(
            f'UPDATE "{model._meta.db_table}" SET source_type = %s WHERE source_type = %s',
            [new, old],
        )


def rename_planetscale_to_planetscale_mysql(apps, schema_editor) -> None:
    _rename_source_type(apps, schema_editor, old=_OLD_SOURCE_TYPE, new=_NEW_SOURCE_TYPE)


def rename_planetscale_mysql_to_planetscale(apps, schema_editor) -> None:
    _rename_source_type(apps, schema_editor, old=_NEW_SOURCE_TYPE, new=_OLD_SOURCE_TYPE)


class Migration(migrations.Migration):
    """Rename the stored `PlanetScale` source type to `PlanetScaleMySQL`.

    Split out from 0123 so the data update never shares a transaction with schema operations. The
    MySQL source shipped a day before this rename, so the matching row count is small and a single
    indexed-free UPDATE is cheaper than batching it.
    """

    dependencies = [
        ("warehouse_sources", "0123_alter_externaldatasource_source_type_and_more"),
    ]

    operations = [
        migrations.RunPython(
            rename_planetscale_to_planetscale_mysql,
            reverse_code=rename_planetscale_mysql_to_planetscale,
            elidable=True,
        ),
    ]
