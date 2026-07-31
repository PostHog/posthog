# Warehouse sources presentation layer

The source and schema management API — `external_data_source.py`, `external_data_schema.py`,
`source_api_versions.py`, `public_source_configs.py` — lives here alongside the
`warehouse_sources` models it serves. Routes are registered in
`products/warehouse_sources/backend/routes.py`.

## The presentation layer stays source-agnostic

These views must not branch on a concrete source type — see
[`products/data_warehouse/backend/presentation/README.md`](../../../data_warehouse/backend/presentation/README.md)
for the rule, where behaviour goes instead, and the `check-dwh-source-agnostic.py` CI guard
(which scans this directory too).
