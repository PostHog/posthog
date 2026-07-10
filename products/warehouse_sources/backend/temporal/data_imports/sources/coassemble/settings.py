from dataclasses import dataclass, field


@dataclass
class CoassembleEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Trackings can only be listed per course (`id` is a required query param), so the endpoint
    # fans out over the workspace's courses.
    fan_out_by_course: bool = False


# Coassemble Headless API list endpoints (https://developers.coassemble.com). All are full refresh
# only: the courses/collections/clients/users lists expose no server-side timestamp filter, and the
# trackings `start`/`end` params filter on mutable progress timestamps (`commenced`/`completed`)
# that we could not smoke-test against a live workspace, so we conservatively re-pull and let merge
# dedupe on the primary key.
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
        path="/trackings",
        primary_keys=["course_id", "id"],
        fan_out_by_course=True,
    ),
}

ENDPOINTS = tuple(COASSEMBLE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
