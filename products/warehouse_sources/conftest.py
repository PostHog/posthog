import os
import sys

# When `backend:test` runs from products/warehouse_sources/, that directory lands on sys.path, which
# makes the product's own packages importable under a truncated top-level name (`backend.temporal...`)
# in addition to the canonical `products.warehouse_sources.backend.temporal...`. Anything resolved
# through the truncated name gets a *second* copy of every class/function, so a `mock.patch` on the
# canonical module silently misses code that went through the other one (e.g. a source registered
# under `backend...` while a test patches `products.warehouse_sources...`, which manifests as a real
# network connection sneaking past the mock). Drop this directory from sys.path so only the canonical
# package path resolves — matching how the Django Temporal segment runs the same tests (from repo root).
_here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != _here]
