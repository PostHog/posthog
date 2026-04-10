"""Public infrastructure surface for Error tracking.

This package exposes ClickHouse schema constants and embedding table metadata
that must cross the product boundary for things like ClickHouse migrations,
central schema registration, and embedding cleanup jobs.

It is *not* a business facade. Prefer ``backend.facade`` for anything that
exposes product behavior — ``backend.infra`` is the sanctioned path for raw
DDL/table-metadata constants only.
"""
