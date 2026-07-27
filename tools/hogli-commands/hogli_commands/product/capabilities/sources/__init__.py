"""Per-surface derivation modules.

Every module exposes ``derive(ctx) -> dict[str, SurfaceFact]`` keyed by product directory
name, and must return an entry for *every* product in ``ctx.product_dirs``. Omitting a
product is a bug: a consumer cannot distinguish a missing key from a negative answer.
``unknown(reason)`` is how a source says "I don't know".
"""
