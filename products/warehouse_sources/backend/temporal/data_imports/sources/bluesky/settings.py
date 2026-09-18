from products.warehouse_sources.backend.types import IncrementalField

# Bluesky's public AppView (see `bluesky.py`). No auth is required for any of the endpoints below.
BASE_URL = "https://public.api.bsky.app"

ENDPOINTS = (
    "Profile",
    "Posts",
    "Followers",
    "Follows",
)

# None of these endpoints expose a server-side timestamp filter (e.g. `since`/`updated_after`) --
# they only support opaque cursor pagination -- so every table syncs as a full refresh. Per the
# incremental sync guidance, a client-side "stop when we've seen this id before" cursor would still
# walk every page on every run, so it isn't real incremental sync and isn't worth pretending here.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
