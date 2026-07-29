from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Qualtrics serves every brand from a datacenter-specific host; the API version is a path
# segment under it (`https://{datacenter}.qualtrics.com/API/v3`).
QUALTRICS_API_VERSION = "v3"
QUALTRICS_DEFAULT_DOMAIN_SUFFIX = ".qualtrics.com"

# How an endpoint reaches its rows.
#   "list"          — a brand-wide paginated collection under `result.elements`
#   "survey_query"  — the same collection shape, filtered per survey via a `surveyId` param
#   "survey_path"   — one un-paginated `result.elements` payload per survey, keyed in the path
#   "survey_export" — the async response-export pipeline (create job -> poll -> download zip)
FetchMode = Literal["list", "survey_query", "survey_path", "survey_export"]


@dataclass(frozen=True)
class QualtricsEndpointConfig:
    name: str
    # Path under `/API/{version}`. `{survey_id}` is substituted per parent survey.
    path: str
    primary_key: list[str]
    fetch_mode: FetchMode = "list"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field, never a `lastModified`-style column that would rewrite
    # partitions on every sync.
    partition_key: str | None = None

    @property
    def fans_out_over_surveys(self) -> bool:
        return self.fetch_mode != "list"


RECORDED_DATE_INCREMENTAL = incremental_field("recordedDate")

QUALTRICS_ENDPOINTS: dict[str, QualtricsEndpointConfig] = {
    "surveys": QualtricsEndpointConfig(
        name="surveys",
        path="/surveys",
        primary_key=["id"],
        # `lastModified` is returned but Qualtrics exposes no modified-since filter on the
        # collection, so a cursor here would still walk every page — full refresh only.
        partition_key="creationDate",
    ),
    "users": QualtricsEndpointConfig(
        name="users",
        path="/users",
        primary_key=["id"],
    ),
    "groups": QualtricsEndpointConfig(
        name="groups",
        path="/groups",
        primary_key=["id"],
    ),
    "divisions": QualtricsEndpointConfig(
        name="divisions",
        path="/divisions",
        primary_key=["divisionId"],
    ),
    "distributions": QualtricsEndpointConfig(
        name="distributions",
        path="/distributions",
        # Distributions are listed per survey, so the survey id is part of the row identity.
        primary_key=["surveyId", "id"],
        fetch_mode="survey_query",
    ),
    "survey_questions": QualtricsEndpointConfig(
        name="survey_questions",
        path="/survey-definitions/{survey_id}/questions",
        primary_key=["surveyId", "QuestionID"],
        fetch_mode="survey_path",
    ),
    "survey_responses": QualtricsEndpointConfig(
        name="survey_responses",
        path="/surveys/{survey_id}/export-responses",
        primary_key=["surveyId", "responseId"],
        fetch_mode="survey_export",
        # `startDate` on the export request filters server-side on `recordedDate`.
        incremental_fields=[RECORDED_DATE_INCREMENTAL],
        partition_key="recordedDate",
    ),
}

ENDPOINTS = tuple(QUALTRICS_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in QUALTRICS_ENDPOINTS.items()
}

# Endpoint probed during per-schema credential validation. Fan-out endpoints have no reachable
# URL without a survey id, so they validate through the survey list instead.
VALIDATION_PATHS: dict[str, str] = {
    name: "/surveys" if config.fans_out_over_surveys else config.path for name, config in QUALTRICS_ENDPOINTS.items()
}
