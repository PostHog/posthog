# Warehouse source vendors

This tree holds warehouse source vendors, one directory per vendor. Team warehouse-sources owns it.
New vendors go here, not under `products/warehouse_sources/backend/temporal/data_imports/sources/`.
Vendors that other code imports (core-coupled vendors) stay in the product.

## One directory is one vendor

```text
sources/<vendor>/
  __init__.py      # required: tach, grimp and pytest only see regular packages
  source.py        # the source class, registered with SourceRegistry
  _config.py       # generated config (pnpm generate:source-configs)
  tests/
    __init__.py
    test_<vendor>.py
```

The loader finds `sources/<vendor>/source.py` on its own. There is no import list to edit.
A new vendor still needs its `ExternalDataSourceType` enum member.
`sources/source.template` has the steps. Read the `implementing-warehouse-sources` skill before you build or extend a source.

## Imports

Import shared code only from `sources.sdk`. Tests can also import from `sources.sdk.testing`.
Import your own directory as `sources.<vendor>`. Do not import another vendor.
tach (`sources.*` in `tach.toml`) checks vendor code, and import-linter (`pyproject.toml`) also checks vendor tests.
If you need a shared name that the SDK does not have, add it to `sources/sdk/__init__.py` (or `testing.py`) from its origin module.
`sources/sdk/internals.py` holds names from product modules that tach does not expose. Do not add to it if a module that the product exposes has the name.
A `mock.patch` target names the origin module, not `sources.sdk`: a patch on a re-export changes nothing.

## Tests

The source test rules in `products/warehouse_sources/backend/temporal/data_imports/sources/AGENTS.md` apply here too.

Vendor tests run with the Django test config of the repo, the same way as the product tests:

```sh
hogli test sources/<vendor>/
```

`sources/conftest.py` gives the vendor tests the fixtures of the product tests and caps `time.sleep`, so retry backoff does not run at real duration.
CI runs these tests in the `warehouse_sources` product job (`products/warehouse_sources/package.json`, `backend:test`).
