from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

API_SPEC_URL = "https://api.statsig.com/openapi/20240601.json"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "gates": {
        "description": "Feature gates with targeting rules, status, and rollout settings.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "id": "Unique gate identifier.",
            "name": "Gate display name.",
            "createdTime": "Timestamp when the gate was created.",
            "lastModifiedTime": "Timestamp of the last gate change.",
            "isEnabled": "Whether the gate is enabled.",
            "rules": "Targeting rules used to evaluate the gate.",
        },
    },
    "experiments": {
        "description": "Experiments with groups, allocation, metrics, and lifecycle status.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "id": "Unique experiment identifier.",
            "name": "Experiment display name.",
            "createdTime": "Timestamp when the experiment was created.",
            "lastModifiedTime": "Timestamp of the last experiment change.",
            "groups": "Experiment groups and their parameter values.",
            "layerID": "Identifier of the layer that contains the experiment.",
        },
    },
    "dynamic_configs": {
        "description": "Dynamic configurations with default values, targeting rules, and enabled status.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "id": "Unique configuration identifier.",
            "name": "Configuration display name.",
            "createdTime": "Timestamp when the configuration was created.",
            "lastModifiedTime": "Timestamp of the last configuration change.",
            "rules": "Targeting rules for configuration values.",
        },
    },
    "layers": {
        "description": "Experiment layers with shared parameters and ownership metadata.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "id": "Unique layer identifier.",
            "name": "Layer display name.",
            "createdTime": "Timestamp when the layer was created.",
            "lastModifiedTime": "Timestamp of the last layer change.",
            "parameters": "Parameters defined in the layer.",
        },
    },
    "segments": {
        "description": "User segments defined by rules or identifier lists.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "id": "Unique segment identifier.",
            "name": "Segment display name.",
            "createdTime": "Timestamp when the segment was created.",
            "lastModifiedTime": "Timestamp of the last segment change.",
            "type": "Whether the segment uses rules or an identifier list.",
        },
    },
    "metrics": {
        "description": "Metric definitions with types, directionality, and event lineage. This table does not contain measured values.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "id": "Unique metric identifier.",
            "name": "Metric name.",
            "type": "Metric aggregation type.",
            "directionality": "Whether an increase or decrease in the metric is desirable.",
            "lineage": "Events and metrics used by the metric definition.",
        },
    },
    "audit_logs": {
        "description": "Project changes with action types, affected objects, and the members who made them.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "id": "Unique audit entry identifier.",
            "actionType": "Type of action recorded in the audit entry.",
            "date": "Date of the action.",
            "time": "Time of the action, including timezone information.",
            "updatedByUserID": "Identifier of the member who made the change.",
            "changes": "Changes recorded by the action.",
        },
    },
    "users": {
        "description": "Statsig project members and their roles. This table does not contain tracked end users.",
        "docs_url": API_SPEC_URL,
        "columns": {
            "userID": "Unique member identifier.",
            "email": "Member email address.",
            "firstName": "Member first name.",
            "lastName": "Member last name.",
            "role": "Member role in the project.",
        },
    },
}
