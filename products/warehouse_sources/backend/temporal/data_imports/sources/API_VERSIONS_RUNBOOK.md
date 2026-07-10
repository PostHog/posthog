# Runbook: updating a warehouse source to a new vendor API version

Audience: support and on-call. For implementing a new version in code, see the `warehouse-source-new-version` skill instead.

## How versions work

- Each source type declares the vendor API versions it supports, a default, and any vendor deprecations (`supported_versions`, `default_version`, `deprecated_versions` on the source class in `sources/<dir>/source.py`). Sources whose vendor has no meaningful API versioning show `v1`.
- Each connected source (an `ExternalDataSource` row) is **pinned** to one version in its `api_version` column. Syncs always run with the pinned version; a missing pin falls back to the source type's default. New sources are pinned to the default at creation.
- Version labels are vendor strings ("2024-09-30.acacia", "v2", "2022-06-28") — copy them exactly.

## Reading a customer's pinned version

- API: `GET /api/environments/:team_id/external_data_sources/:id/` → `api_version` (and `api_version_deprecation` when the vendor has deprecated it).
- HogQL (works in the customer's project, or via internal tooling):

  ```sql
  SELECT id, source_type, api_version, prefix FROM data_warehouse_sources WHERE deleted = 0
  ```

- Supported versions per source type: `GET /api/public_source_configs/` → `versions`, `defaultVersion`, `deprecatedVersions`, `apiDocsUrl`.

## Changing a customer's pinned version

1. Confirm the target version is in the source type's `supported_versions` (public source configs, above).
2. Update the pin — Django shell on the relevant region (there is deliberately no user-facing setter):

   ```python
   from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
   source = ExternalDataSource.objects.get(id="<source uuid>")
   source.api_version = "<new version label>"
   source.save(update_fields=["api_version"])
   ```

3. If the version bump ships with a migration script in its PR (deprecation PRs always do), prefer running that script — it may include schema/data transforms beyond the repin. Read it first; those scripts are written to be reviewed and run by a human, never automatically.

## Verifying a sync after switching

1. Trigger a sync for one schema of the source (source page → Schemas tab → sync now), or wait for the next scheduled run.
2. Watch the run on the Syncs tab; confirm it completes and row counts look sane.
3. Spot-check the synced table in SQL — especially fields the vendor renamed/removed between versions (the version PR's description lists them).
4. If schema drift is expected (vendor renamed columns), the first sync after repinning may add new columns; ask the customer to update saved queries that referenced renamed fields.

## Rolling back

Set `api_version` back to the previous label (same shell steps) and re-trigger a sync. Old versions stay implemented and functional — removing one is an explicit decision that would be its own PR — so rollback is always available unless the vendor has already sunset the old version server-side.

## Deprecations

- When a vendor deprecates a version we support, the source class gains deprecation metadata, and every pinned source shows a warning banner on its page (with the sunset date when announced) plus `api_version_deprecation` in the API. Impacted teams may also receive a deprecation email.
- Helping a customer migrate before sunset: follow "Changing a customer's pinned version" above, using the deprecation PR's migration script where one exists. Do this well before the sunset date so there is room to verify and roll back.
- At sunset, the vendor starts rejecting requests under the old version — syncs fail with vendor-side errors (the pin does not change by itself, and PostHog does not auto-repin). The fix is the same migration, now urgent.

## Escalate to the team when

- The migration script for a deprecation is marked lossy/manual, or there is no script.
- A sync fails under the new version with schema/transform errors (not credentials).
- The customer relies on fields that the new vendor version removed.
- A vendor announces a sunset for a version we still default to.
