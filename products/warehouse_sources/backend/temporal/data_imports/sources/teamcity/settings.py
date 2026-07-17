from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# TeamCity pages with the `count` locator dimension; the server batches at ~100 by default
# but accepts larger counts. Occurrence rows are small, so we fetch them in bigger pages.
DEFAULT_PAGE_SIZE = 100
OCCURRENCE_PAGE_SIZE = 1000

# Hard cap on pages fetched per parent build during occurrence fan-out, to bound runaway
# pagination. A structured warning is logged if the cap is reached.
MAX_PAGES_PER_BUILD = 100

# Hard cap on pages fetched in a single pagination walk. nextHref comes from the remote
# server, so a misbehaving or malicious host could otherwise return a non-empty cursor
# forever and pin an import worker until the activity timeout. At 100–1000 rows per page
# this still allows tens of millions of rows per walk before the cap trips.
MAX_PAGES_PER_WALK = 50_000

# Hard cap on a single response body. The server URL is customer-supplied, so a hostile or
# misbehaving host could otherwise return an unbounded body that `response.json()` buffers
# and exhaust an import worker's memory. A page of ~1000 rich rows is a few MiB, so 128 MiB
# leaves ample headroom for legitimate pages while bounding memory.
MAX_RESPONSE_BYTES = 128 * 1024 * 1024

# Wall-clock cap on downloading a single response body. `requests`' read timeout only bounds an
# idle socket, so a hostile host can trickle one byte before each timeout to hold the read open
# indefinitely while staying under MAX_RESPONSE_BYTES. This monotonic deadline bounds that. A
# page of a few MiB downloads in well under a second, so 300s leaves ample headroom for a large
# legitimate page on a slow link while stopping a malicious host from pinning an import worker.
MAX_RESPONSE_DOWNLOAD_SECONDS = 300

# Chunk size for the bounded, deadline-checked body read. Small enough to re-check the byte cap
# and download deadline frequently, large enough that legitimate pages read in a few iterations.
DOWNLOAD_CHUNK_BYTES = 1024 * 1024

# Builds locator applied to the builds endpoint and to the parent walk of the occurrence
# fan-outs. `branch:(default:any)` lifts TeamCity's default-branch-only filter so feature
# branch builds are synced too; `state:finished` keeps rows immutable (a running build's
# finishDate would change under us). TeamCity's default filter still excludes canceled and
# personal builds.
BUILDS_LOCATOR_DEFAULTS: dict[str, str] = {
    "branch": "(default:any)",
    "state": "finished",
}

# Synthetic columns injected onto occurrence rows from the parent build during fan-out.
FAN_OUT_BUILD_ID_FIELD = "build_id"
FAN_OUT_BUILD_FINISH_DATE_FIELD = "build_finish_date"


def _finish_date_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "finishDate",
            "type": IncrementalFieldType.DateTime,
            "field": "finishDate",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


def _build_finish_date_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "build finish date",
            "type": IncrementalFieldType.DateTime,
            "field": FAN_OUT_BUILD_FINISH_DATE_FIELD,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class TeamCityEndpointConfig:
    name: str
    path: str  # Path under /app/rest, e.g. "/builds"
    # Root key of the entity list in the JSON response (e.g. "build", "vcs-root").
    response_key: str
    # TeamCity `fields` spec requesting a richer payload than the default stubs. Unknown
    # field names are silently ignored by the server, so this can never 400.
    fields: str
    # The endpoint's locator exposes a server-side filter usable as an incremental cursor
    # (builds: finishDate condition:after; changes: sinceChange; occurrences: bounded via
    # the parent builds walk). Everything else is full refresh.
    supports_incremental: bool
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Extra locator dimensions always sent with list requests (e.g. defaultFilter:false).
    locator_defaults: dict[str, str] = field(default_factory=dict)
    # Timestamp columns in TeamCity's compact format (20260715T160948+0000), parsed to
    # datetimes at the source so incremental watermarks and datetime partitioning work.
    timestamp_fields: list[str] = field(default_factory=list)
    # Stable field to partition by. None when the resource has no reliable timestamp.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # TeamCity list endpoints return newest-first and expose no sort control.
    sort_mode: Literal["asc", "desc"] = "desc"
    page_size: int = DEFAULT_PAGE_SIZE
    # Fan-out: occurrences can only be listed scoped to a build, so they are fetched by
    # walking the builds endpoint and querying this child once per build.
    fan_out_over_builds: bool = False
    should_sync_default: bool = True


TEAMCITY_ENDPOINTS: dict[str, TeamCityEndpointConfig] = {
    "projects": TeamCityEndpointConfig(
        name="projects",
        path="/projects",
        response_key="project",
        fields="count,nextHref,project(id,name,description,parentProjectId,archived,virtual,webUrl)",
        # The project locator has no timestamp dimension; project lists are tiny anyway.
        supports_incremental=False,
    ),
    "build_types": TeamCityEndpointConfig(
        name="build_types",
        path="/buildTypes",
        response_key="buildType",
        fields="count,nextHref,buildType(id,name,description,projectName,projectId,paused,templateFlag,webUrl)",
        supports_incremental=False,
    ),
    "agents": TeamCityEndpointConfig(
        name="agents",
        path="/agents",
        response_key="agent",
        fields=(
            "count,nextHref,agent(id,name,typeId,connected,enabled,authorized,uptodate,outdated,"
            "ip,version,currentAgentVersion,lastActivityTime,idleSinceTime,registrationTimestamp,"
            "os,osType,cpuRank,pool(id,name))"
        ),
        supports_incremental=False,
        # The default agent locator only returns connected, authorized agents; lift it so the
        # whole fleet (disconnected/unauthorized agents included) is visible in the warehouse.
        locator_defaults={"defaultFilter": "false"},
        timestamp_fields=["lastActivityTime", "idleSinceTime", "registrationTimestamp"],
    ),
    "vcs_roots": TeamCityEndpointConfig(
        name="vcs_roots",
        path="/vcs-roots",
        response_key="vcs-root",
        fields="count,nextHref,vcs-root(id,name,vcsName,modificationCheckInterval,project(id,name))",
        supports_incremental=False,
    ),
    "builds": TeamCityEndpointConfig(
        name="builds",
        path="/builds",
        response_key="build",
        fields=(
            "count,nextHref,build(id,buildTypeId,number,status,state,branchName,defaultBranch,"
            "personal,composite,failedToStart,queuedDate,startDate,finishDate,statusText,webUrl,"
            "agent(id,name,typeId),triggered(type,date,user(id,username,name)))"
        ),
        # `finishDate:(date:<cursor>,condition:after)` filters server-side and is preserved
        # across nextHref pages, so incremental syncs only fetch newly finished builds.
        supports_incremental=True,
        incremental_fields=_finish_date_incremental_fields(),
        locator_defaults=dict(BUILDS_LOCATOR_DEFAULTS),
        timestamp_fields=["queuedDate", "startDate", "finishDate"],
        # finishDate is immutable for finished builds (the only state we sync) and aligns
        # with the incremental cursor.
        partition_key="finishDate",
    ),
    "changes": TeamCityEndpointConfig(
        name="changes",
        path="/changes",
        response_key="change",
        fields=(
            "count,nextHref,change(id,version,username,date,comment,webUrl,"
            "user(id,username,name),vcsRootInstance(id,vcs-root-id))"
        ),
        # `sinceChange:(id:<cursor>)` filters server-side (verified: an id above the newest
        # change returns 0 rows), so the change id is the incremental cursor.
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "id",
                "type": IncrementalFieldType.Integer,
                "field": "id",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        timestamp_fields=["date"],
        partition_key="date",
    ),
    "test_occurrences": TeamCityEndpointConfig(
        name="test_occurrences",
        path="/testOccurrences",
        response_key="testOccurrence",
        fields=(
            "count,nextHref,testOccurrence(id,name,status,duration,runOrder,muted,currentlyMuted,"
            "currentlyInvestigated,ignored,newFailure,build(id,buildTypeId),test(id,name))"
        ),
        # Bounded at the parent: the builds walk is windowed with the finishDate locator from
        # the child's build_finish_date watermark, so incremental syncs only fan out over
        # newly finished builds.
        supports_incremental=True,
        incremental_fields=_build_finish_date_incremental_fields(),
        partition_key=FAN_OUT_BUILD_FINISH_DATE_FIELD,
        # The occurrence id embeds the build id ("build:(id:123),id:2000000001"), so it is
        # unique table-wide despite being a fan-out child.
        primary_keys=["id"],
        page_size=OCCURRENCE_PAGE_SIZE,
        fan_out_over_builds=True,
        # One request per build (more for test-heavy builds): a first sync fans out over the
        # server's whole retained build history. Off by default so connecting a source
        # doesn't silently start a very expensive crawl; users opt in deliberately.
        should_sync_default=False,
    ),
    "problem_occurrences": TeamCityEndpointConfig(
        name="problem_occurrences",
        path="/problemOccurrences",
        response_key="problemOccurrence",
        fields=(
            "count,nextHref,problemOccurrence(id,type,identity,muted,currentlyMuted,"
            "currentlyInvestigated,newFailure,build(id,buildTypeId),problem(id,type,identity))"
        ),
        supports_incremental=True,
        incremental_fields=_build_finish_date_incremental_fields(),
        partition_key=FAN_OUT_BUILD_FINISH_DATE_FIELD,
        primary_keys=["id"],
        page_size=OCCURRENCE_PAGE_SIZE,
        fan_out_over_builds=True,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(TEAMCITY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TEAMCITY_ENDPOINTS.items()
}
