from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class LaceworkEndpointConfig:
    name: str
    # Path relative to https://{account}.lacework.net/api/v2, e.g. "/Alerts" or
    # "/Vulnerabilities/Hosts/search". GET endpoints take startTime/endTime query params;
    # POST search endpoints take a `timeFilter` object in the request body.
    path: str
    method: Literal["GET", "POST"] = "POST"
    # Row field the server-side time window filters on. Every Lacework list/search endpoint is
    # windowed (max 7 days per request), so this doubles as the incremental cursor field.
    time_filter_field: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Merge sync (dedupe on primary_keys) is only offered where the API exposes a unique row id.
    supports_incremental: bool = False
    supports_append: bool = False
    primary_keys: Optional[list[str]] = None
    # Stable field to partition by (a created/started timestamp, never a mutating one).
    partition_key: Optional[str] = None
    # Days per request window. The API hard-caps a request's time range at 7 days; high-volume
    # datasets use smaller windows so one result set stays under the 500,000-row cap Lacework
    # applies across all pages of a single request.
    window_days: int = 7
    # First sync / full refresh reaches back this many days instead of full history.
    default_lookback_days: int = 90
    # Required `dataset` body param for /Configs/ComplianceEvaluations/search.
    dataset: Optional[str] = None
    description: Optional[str] = None


def _compliance_endpoint(name: str, dataset: str, provider: str) -> LaceworkEndpointConfig:
    # Compliance evaluation rows have no unique id (one row per resource/recommendation per
    # report), so they sync append-only on reportTime. The API only serves the last 90 days.
    return LaceworkEndpointConfig(
        name=name,
        path="/Configs/ComplianceEvaluations/search",
        dataset=dataset,
        time_filter_field="reportTime",
        incremental_fields=[_datetime_incremental_field("reportTime")],
        supports_append=True,
        partition_key="reportTime",
        default_lookback_days=90,
        description=f"{provider} compliance evaluations. Syncs the last 90 days on first sync or full refresh",
    )


LACEWORK_ENDPOINTS: dict[str, LaceworkEndpointConfig] = {
    "alerts": LaceworkEndpointConfig(
        name="alerts",
        path="/Alerts",
        method="GET",
        time_filter_field="startTime",
        incremental_fields=[_datetime_incremental_field("startTime")],
        supports_incremental=True,
        supports_append=True,
        primary_keys=["alertId"],
        partition_key="startTime",
        default_lookback_days=90,
        description=(
            "Alerts raised by Lacework, filtered by the time the potential threat started. "
            "Status changes on alerts older than the last synced window are only picked up on a full refresh"
        ),
    ),
    "audit_logs": LaceworkEndpointConfig(
        name="audit_logs",
        path="/AuditLogs",
        method="GET",
        time_filter_field="createdTime",
        incremental_fields=[_datetime_incremental_field("createdTime")],
        supports_append=True,
        partition_key="createdTime",
        default_lookback_days=90,
        description="Lacework console audit log entries. Syncs the last 90 days on first sync or full refresh",
    ),
    "agent_info": LaceworkEndpointConfig(
        name="agent_info",
        path="/AgentInfo/search",
        # Agent rows mutate in place (status, lastUpdate) and the search window filters on
        # recent activity, so this is a full-refresh inventory of agents seen in the last 7 days.
        default_lookback_days=7,
        description="Inventory of Lacework agents active in the last 7 days. Full refresh only",
    ),
    "vulnerabilities_hosts": LaceworkEndpointConfig(
        name="vulnerabilities_hosts",
        path="/Vulnerabilities/Hosts/search",
        time_filter_field="startTime",
        incremental_fields=[_datetime_incremental_field("startTime")],
        supports_append=True,
        partition_key="startTime",
        # Host vulnerability assessments are the highest-volume dataset: 1-day windows keep each
        # request's result set under the API's 500k-row cap on large environments.
        window_days=1,
        default_lookback_days=30,
        description=(
            "Host vulnerability assessment results (one row per CVE per machine per assessment). "
            "Syncs the last 30 days on first sync or full refresh"
        ),
    ),
    "vulnerabilities_containers": LaceworkEndpointConfig(
        name="vulnerabilities_containers",
        path="/Vulnerabilities/Containers/search",
        time_filter_field="startTime",
        incremental_fields=[_datetime_incremental_field("startTime")],
        supports_append=True,
        partition_key="startTime",
        window_days=1,
        default_lookback_days=30,
        description=(
            "Container image vulnerability assessment results (one row per CVE per image per assessment). "
            "Syncs the last 30 days on first sync or full refresh"
        ),
    ),
    "compliance_evaluations_aws": _compliance_endpoint("compliance_evaluations_aws", "AwsCompliance", "AWS"),
    "compliance_evaluations_azure": _compliance_endpoint("compliance_evaluations_azure", "AzureCompliance", "Azure"),
    "compliance_evaluations_gcp": _compliance_endpoint("compliance_evaluations_gcp", "GcpCompliance", "GCP"),
    "compliance_evaluations_k8s": _compliance_endpoint("compliance_evaluations_k8s", "K8sCompliance", "Kubernetes"),
    "entities_machines": LaceworkEndpointConfig(
        name="entities_machines",
        path="/Entities/Machines/search",
        time_filter_field="startTime",
        incremental_fields=[_datetime_incremental_field("startTime")],
        supports_append=True,
        partition_key="startTime",
        # One row per machine per activity segment — 1-day windows keep large fleets under the
        # 500k-row-per-request cap.
        window_days=1,
        default_lookback_days=30,
        description=(
            "Machines observed online, one row per machine per activity segment. "
            "Syncs the last 30 days on first sync or full refresh"
        ),
    ),
}

ENDPOINTS = tuple(LACEWORK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LACEWORK_ENDPOINTS.items()
}
