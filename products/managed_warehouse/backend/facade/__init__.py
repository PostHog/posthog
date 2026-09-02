"""Public boundary for the managed warehouse (duckgres/DuckLake) product.

External consumers import from this package only:

- ``models`` — the Django model classes, free of heavy imports so admin and
  setup-time consumers stay cheap.
- ``api`` — the duckgres/DuckLake capability surface (provisioning, backfill
  state, schema naming, session setup).
- ``client`` — the DuckLake query client.
- ``team_state`` — the dual-read team-state module.
- ``temporal`` — workflow/activity registration and workflow input types.

``api``, ``client`` and ``temporal`` pull duckdb/psycopg/temporalio, so keep them
off the ``django.setup()`` path.
"""

__all__: list[str] = []
