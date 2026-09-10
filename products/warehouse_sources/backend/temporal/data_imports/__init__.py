# Load-bearing: keep this package a regular package (not a namespace package).
#
# `backend:test` runs from products/warehouse_sources/ in pytest's default (prepend) import mode.
# Without this file, `data_imports` is a namespace package, so any collected test under `sources/`
# (there are 500+) makes pytest insert this directory onto sys.path and import that test under a
# truncated top-level name. That in turn makes `sources.<vendor>.source` importable as a *second*
# module identity alongside the canonical `products.warehouse_sources.backend.temporal.data_imports.
# sources.<vendor>.source`. Since each source's `@SourceRegistry.register` runs at import time, the
# truncated copy can win the registry slot while tests patch the canonical module — the mock then
# misses and the real source connects (e.g. a live Postgres connection in the data-imports e2e tests).
# Having this __init__.py keeps the package chain unbroken up to the repo root, so every module
# resolves to its single canonical path. Do not delete.
