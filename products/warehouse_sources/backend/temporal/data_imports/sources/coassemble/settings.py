from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# The documented default page size for the list endpoints. We request it explicitly so the
# "short page means last page" termination check compares against the size the server enforces.
PAGE_SIZE = 100
# /usage/clients documents a smaller default; requesting more risks a silently capped page being
# read as the end of the collection.
USAGE_PAGE_SIZE = 50


@dataclass(frozen=True)
class CoassembleFanOut:
    """A child endpoint that can only be listed per parent row, so the sync walks a parent endpoint
    and calls the child once per row."""

    # Key in COASSEMBLE_ENDPOINTS of the endpoint supplying the parent rows.
    parent: str
    # Parent field bound into the child path, and the placeholder in that path it fills.
    resolve_field: str
    param: str
    # Column the parent value is stamped onto each child row as — child rows carry no reference
    # back to the parent they were listed under.
    stamp_column: str


@dataclass(frozen=True)
class CoassembleEndpointConfig:
    name: str
    # Request path; for a fan-out child, a template over the fan-out's `param`.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # None when the endpoint documents no page/length params, so it serves a single page.
    page_size: int | None = PAGE_SIZE
    # Set when rows arrive inside an envelope rather than as a bare JSON array.
    data_selector: str | None = None
    fan_out: CoassembleFanOut | None = None


# Coassemble Headless API list endpoints (https://developers.coassemble.com). All are full refresh
# only: the courses/collections/clients/users lists expose no server-side timestamp filter, the
# trackings `start`/`end` params filter on mutable progress timestamps (`commenced`/`completed`)
# and the usage `start`/`end` params select a consumption window rather than a modified-since
# cutoff — none of which we could smoke-test against a live workspace, so we conservatively
# re-pull and let merge dedupe on the primary key.
COASSEMBLE_ENDPOINTS: dict[str, CoassembleEndpointConfig] = {
    "courses": CoassembleEndpointConfig(name="courses", path="/courses"),
    "collections": CoassembleEndpointConfig(name="collections", path="/collections"),
    # Client objects carry no numeric `id`; `clientIdentifier` is the workspace-unique handle used
    # by every other endpoint to reference them.
    "clients": CoassembleEndpointConfig(name="clients", path="/clients", primary_keys=["clientIdentifier"]),
    # Users are addressable by bare `identifier` (`GET /user/{identifier}`), so it is
    # workspace-unique on its own.
    "users": CoassembleEndpointConfig(name="users", path="/users", primary_keys=["identifier"]),
    # Tracking rows don't include the course they belong to, so the transport injects `course_id`;
    # it is part of the key because tracking `id` uniqueness across courses is undocumented.
    "course_trackings": CoassembleEndpointConfig(
        name="course_trackings",
        path="/trackings?id={id}",
        primary_keys=["course_id", "id"],
        fan_out=CoassembleFanOut(parent="courses", resolve_field="id", param="id", stamp_column="course_id"),
    ),
    # Per-learner screen progress for a course: one row per learner, with the screen attempts and
    # per-question progress nested under `attempts`.
    "screen_trackings": CoassembleEndpointConfig(
        name="screen_trackings",
        path="/screen/trackings?id={id}",
        primary_keys=["course_id", "id"],
        fan_out=CoassembleFanOut(parent="courses", resolve_field="id", param="id", stamp_column="course_id"),
    ),
    "collection_trackings": CoassembleEndpointConfig(
        name="collection_trackings",
        path="/collection/trackings?id={id}",
        primary_keys=["collection_id", "id"],
        fan_out=CoassembleFanOut(parent="collections", resolve_field="id", param="id", stamp_column="collection_id"),
    ),
    # /user/trackings answers for one learner and wraps their course trackings in a per-user
    # envelope, so the rows are the envelope's `trackings` entries.
    "user_trackings": CoassembleEndpointConfig(
        name="user_trackings",
        path="/user/trackings?identifier={identifier}",
        primary_keys=["user_identifier", "id"],
        data_selector="trackings",
        fan_out=CoassembleFanOut(
            parent="users", resolve_field="identifier", param="identifier", stamp_column="user_identifier"
        ),
    ),
    # Consumption rows for every client in the workspace, one per metric per billing period.
    "client_usage": CoassembleEndpointConfig(
        name="client_usage",
        path="/usage/clients",
        primary_keys=["clientIdentifier", "metric", "periodStart"],
        page_size=USAGE_PAGE_SIZE,
        data_selector="data",
    ),
    # The per-client limits behind those consumption rows. Only addressable one client at a time,
    # and the rows name no client, so the fan-out stamps `clientIdentifier` back in.
    "client_allowances": CoassembleEndpointConfig(
        name="client_allowances",
        path="/usage/client/{identifier}",
        primary_keys=["clientIdentifier", "metric", "periodStart"],
        page_size=None,
        fan_out=CoassembleFanOut(
            parent="clients",
            resolve_field="clientIdentifier",
            param="identifier",
            stamp_column="clientIdentifier",
        ),
    ),
}

ENDPOINTS = tuple(COASSEMBLE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
