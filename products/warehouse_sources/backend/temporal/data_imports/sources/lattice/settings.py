from dataclasses import dataclass


@dataclass
class LatticeEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"


# The Lattice Talent API v1 has no server-side incremental filters on any list
# endpoint (Fivetran's connector re-imports every table each sync for the same
# reason), so every stream is an honest full refresh. Per-cycle fan-out streams
# (reviews/reviewees) are a possible follow-up.
LATTICE_ENDPOINTS: dict[str, LatticeEndpointConfig] = {
    "users": LatticeEndpointConfig(
        name="users",
        path="/v1/users",
    ),
    "departments": LatticeEndpointConfig(
        name="departments",
        path="/v1/departments",
    ),
    "goals": LatticeEndpointConfig(
        name="goals",
        path="/v1/goals",
    ),
    "feedbacks": LatticeEndpointConfig(
        name="feedbacks",
        path="/v1/feedbacks",
    ),
    "review_cycles": LatticeEndpointConfig(
        name="review_cycles",
        path="/v1/reviewCycles",
    ),
    "updates": LatticeEndpointConfig(
        name="updates",
        path="/v1/updates",
    ),
}

ENDPOINTS = tuple(LATTICE_ENDPOINTS.keys())
