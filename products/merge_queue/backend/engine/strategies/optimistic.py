"""Optimistic strategy: each PR validated against a fresh master HEAD, merged on its own."""

CONCURRENT = True  # independent trials may run in parallel within a partition
