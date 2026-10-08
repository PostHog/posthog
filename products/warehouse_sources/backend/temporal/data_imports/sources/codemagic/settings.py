from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

CODEMAGIC_V1 = "v1"
CODEMAGIC_V3 = "v3"
SUPPORTED_VERSIONS = (CODEMAGIC_V1, CODEMAGIC_V3)
DEFAULT_VERSION = CODEMAGIC_V3

BASE_URL = "https://api.codemagic.io"
# v3 is served from the main host under /api/v3, not from the legacy api. subdomain.
V3_BASE_URL = "https://codemagic.io"
V3_PAGE_SIZE = 100
# v3 has no account-wide build list, only GET /teams/{team_id}/builds, so builds fan out over
# the teams the token's user belongs to.
V3_TEAMS_PATH = "/api/v3/user/teams"


@dataclass
class CodemagicEndpointConfig:
    name: str
    path: str
    # Top-level key the list of records lives under in the response body.
    data_selector: str
    # Stable creation-timestamp field to partition Delta storage by, or None to skip partitioning.
    partition_key: Optional[str] = None


ENDPOINTS: dict[str, CodemagicEndpointConfig] = {
    "Applications": CodemagicEndpointConfig(
        name="Applications",
        path="/apps",
        data_selector="applications",
    ),
    "Builds": CodemagicEndpointConfig(
        name="Builds",
        path="/builds",
        # GET /builds is undocumented in Codemagic's current public REST API reference (only
        # POST /builds and GET /builds/:id are documented there:
        # https://docs.codemagic.io/rest-api/builds/). A live probe against
        # api.codemagic.io/builds returns 401 (auth required) rather than 404, confirming the
        # endpoint exists, and community-reported responses
        # (https://github.com/orgs/codemagic-ci-cd/discussions/1941) show the underlying build
        # object shape (_id, appId, status, createdAt, ...). The "builds" response wrapper key is
        # inferred from the vendor's consistent {resource_plural: [...]} convention used by the
        # documented GET /apps endpoint — adjust `data_selector` if the vendor's actual key differs.
        data_selector="builds",
        partition_key="createdAt",
    ),
}

V3_ENDPOINTS: dict[str, CodemagicEndpointConfig] = {
    "Applications": CodemagicEndpointConfig(
        name="Applications",
        path="/api/v3/user/apps",
        data_selector="data",
    ),
    "Builds": CodemagicEndpointConfig(
        name="Builds",
        path="/api/v3/teams/{team_id}/builds",
        data_selector="data",
        partition_key="created_at",
    ),
}

# Neither endpoint exposes a server-side created/updated-since filter — GET /builds has no
# documented timestamp filter param, only the `skip` offset — so both tables are full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
