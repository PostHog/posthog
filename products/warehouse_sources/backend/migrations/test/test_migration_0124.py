import importlib

import pytest

from django.apps import apps
from django.db import connection

from products.warehouse_sources.backend.facade.models import ExternalDataSource, PendingSourceCredential

migration_module = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0124_rename_planetscale_source_type_to_mysql"
)
forwards = migration_module.rename_planetscale_to_planetscale_mysql
backwards = migration_module.rename_planetscale_mysql_to_planetscale


class _SchemaEditor:
    """The migration writes raw SQL, so it needs something that can execute it."""

    def execute(self, sql, params=None):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


def _source(team, source_type):
    return ExternalDataSource.objects.create(source_id="src", connection_id="conn", team=team, source_type=source_type)


def _credential(team, source_type):
    # `PendingSourceCredential` is fail-closed team-scoped: its default manager raises
    # `TeamScopeError` outside a request that set an ambient team scope. The migration this covers
    # updates every team's rows anyway, so the fixture writes through `unscoped()`.
    return PendingSourceCredential.objects.unscoped().create(team=team, source_type=source_type, payload={})


@pytest.mark.django_db
class TestRenamePlanetScaleSourceType:
    def test_forwards_renames_only_planetscale_rows(self, team):
        planetscale = _source(team, "PlanetScale")
        mysql = _source(team, "MySQL")
        credential = _credential(team, "PlanetScale")

        forwards(apps, _SchemaEditor())

        planetscale.refresh_from_db()
        mysql.refresh_from_db()
        credential.refresh_from_db()
        assert planetscale.source_type == "PlanetScaleMySQL"
        assert credential.source_type == "PlanetScaleMySQL"
        # A plain MySQL source shares neither product nor value, so it must be left alone.
        assert mysql.source_type == "MySQL"

    def test_backwards_restores_the_old_value(self, team):
        source = _source(team, "PlanetScale")
        credential = _credential(team, "PlanetScale")

        forwards(apps, _SchemaEditor())
        backwards(apps, _SchemaEditor())

        source.refresh_from_db()
        credential.refresh_from_db()
        assert source.source_type == "PlanetScale"
        assert credential.source_type == "PlanetScale"

    def test_backwards_leaves_the_postgres_source_type_alone(self, team):
        # The Postgres source is new in this change, so rolling the rename back must not fold it
        # into a value that only ever meant the MySQL product.
        postgres = _source(team, "PlanetScalePostgres")

        backwards(apps, _SchemaEditor())

        postgres.refresh_from_db()
        assert postgres.source_type == "PlanetScalePostgres"
