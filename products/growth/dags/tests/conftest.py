# Register the shared Dagster PostgreSQL fixtures so that execute_in_process
# calls use PostgreSQL instead of SQLite (avoids locking errors).
pytest_plugins = ["posthog.dags.tests.dagster_pg_fixtures"]
