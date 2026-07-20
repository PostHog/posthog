# Cache key for cross_region_flag_sync's EU mirror of PostHog's own (US team 2) flag
# definitions. Deliberately non-numeric — a real Team.id is always an int, so this can
# never collide with a real team's key in flag_definitions_hypercache's per-team keyspace.
# Lives in its own leaf module (no imports of its own) so both sdk_cache_provider.py and
# local_evaluation.py can depend on it without either depending on the other — importing
# it never triggers the circular import chain that local_evaluation.py's own import does
# (see sdk_cache_provider._get_hypercache).
EU_CROSS_REGION_MIRROR_CACHE_KEY = "cross-region-flags-mirror"
