from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KernelEndpointConfig:
    name: str
    path: str
    # Kernel object ids are globally unique per resource, so `id` is the natural key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Extra query params merged into every request (e.g. browsers needs status=all to
    # include soft-deleted sessions - the list defaults to status=active otherwise).
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True
    description: Optional[str] = None


# All Kernel list endpoints share offset pagination (limit/offset query params, X-Has-More /
# X-Next-Offset response headers). None of these are synced incrementally: Kernel documents a
# `since` filter on /invocations, but it could not be verified against a live API for this alpha
# release (server-side filtering and response ordering both need a smoke test before the pipeline
# can trust a watermark), so every table ships as a full refresh. See kernel.py for the follow-up note.
KERNEL_ENDPOINTS: dict[str, KernelEndpointConfig] = {
    "apps": KernelEndpointConfig(
        name="apps",
        path="/apps",
        description="Deployed browser-automation apps registered in your Kernel organization.",
    ),
    "deployments": KernelEndpointConfig(
        name="deployments",
        path="/deployments",
        description="Deployment history for your apps, including status and region.",
    ),
    "invocations": KernelEndpointConfig(
        name="invocations",
        path="/invocations",
        description="Action run history: status, payload, output, and start/finish timestamps.",
    ),
    "browsers": KernelEndpointConfig(
        name="browsers",
        path="/browsers",
        # /browsers defaults to status=active; status=all also returns soft-deleted sessions.
        extra_params={"status": "all"},
        description="Cloud browser sessions, including active and soft-deleted sessions.",
    ),
    "profiles": KernelEndpointConfig(
        name="profiles",
        path="/profiles",
        description="Saved browser profiles (persisted cookies, storage, and auth state).",
    ),
}

ENDPOINTS = tuple(KERNEL_ENDPOINTS.keys())
