#!/usr/bin/env python3
# ruff: noqa: T201
"""
showcase/scripts/partition_shards.py
Deterministically partitions 100% of all PostHog backend test files across the
monorepo into N balanced shards (default: 5).
Maps to workflows/ci-backend.yml test coverage:
  Shard 1: Core Authentication, Org & Django Framework
  Shard 2: Core Models, Settings, Scoping Invariants & Multi-DB
  Shard 3: Warehouse Sources Engine, Temporal Pipeline & Queues
  Shard 4: Warehouse Sources Catalogs, CDC & Ingestion
  Shard 5: Products (Product Analytics, Surveys, Batch Exports, MCP Store, Tasks)
"""

import functools
import os
import sys

EXCLUDE_DIRS = {
    "node_modules",
    ".venv",
    ".git",
    "dist",
    "__pycache__",
    ".turbo",
    "staticfiles",
    ".pytest_cache",
    ".ruff_cache",
    "user_scripts",
    "rust_integration",
    "desktop",
    "packages",
    "async_migrations",
}


@functools.lru_cache(maxsize=1)
def get_all_test_files():
    test_files = []
    for root_dir in ["posthog", "ee", "products"]:
        if not os.path.exists(root_dir):
            continue
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            if (
                root.startswith("posthog/dags")
                or root.startswith("posthog/async_migrations")
                or root.startswith("posthog/user_scripts")
                or "products/desktop" in root
            ):
                continue
            for f in files:
                if (
                    f.endswith(".py")
                    and not f.endswith("__init__.py")
                    and not f.endswith("conftest.py")
                    and f != "test_cases_discovery.py"
                ):
                    if f.startswith("test_") or f.endswith("_test.py"):
                        test_files.append(os.path.join(root, f))
    return sorted(test_files)


def chunk(lst, n):
    if n <= 0 or not lst:
        return []
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m) : (i + 1) * k + min(i + 1, m)] for i in range(n)]


def get_shard_files(shard_idx, total_shards=5):
    all_files = get_all_test_files()
    temporal = [f for f in all_files if f.startswith("posthog/temporal")]
    core = [
        f
        for f in all_files
        if (f.startswith("posthog/") or f.startswith("ee/")) and not f.startswith("posthog/temporal")
    ]
    wh = [f for f in all_files if f.startswith("products/warehouse_sources/")] + temporal
    prod = [
        f
        for f in all_files
        if not (f.startswith("posthog/") or f.startswith("ee/") or f.startswith("products/warehouse_sources/"))
    ]

    if total_shards == 5:
        # Shard 1 & 2: Core (split into 2 shards)
        core_shards = chunk(core, 2)
        # Shard 3 & 4: Warehouse Sources + Temporal (split into 2 shards)
        wh_shards = chunk(wh, 2)
        # Shard 5: Products (1 shard)
        prod_shards = [prod]
        all_shards = core_shards + wh_shards + prod_shards
    else:
        all_shards = chunk(all_files, total_shards)

    idx = shard_idx - 1
    if 0 <= idx < len(all_shards):
        return all_shards[idx]
    return []


def main():
    if len(sys.argv) < 2:
        print("Usage: partition_shards.py <shard_index_1_based> [total_shards]", file=sys.stderr)
        sys.exit(1)

    shard_idx = int(sys.argv[1])
    total_shards = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    files = get_shard_files(shard_idx, total_shards)
    print(" ".join(files))


if __name__ == "__main__":
    main()
