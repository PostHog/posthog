# Import the shared Dagster PostgreSQL fixtures so that execute_in_process
# calls use PostgreSQL instead of SQLite (avoids locking errors).
# Direct import (rather than pytest_plugins) is required because pytest
# disallows pytest_plugins in non-top-level conftest files.
from posthog.dags.tests.dagster_pg_fixtures import (  # noqa: F401
    _dagster_postgres_instance,
    _use_postgres_dagster_instance,
)
