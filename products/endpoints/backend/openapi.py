from django.conf import settings

from rest_framework.request import Request

from products.endpoints.backend.logic.strategies import InsightEndpointStrategy
from products.endpoints.backend.models import Endpoint, EndpointVersion, _breakdown_property_names
from products.product_analytics.backend.models.insight_variable import InsightVariable

INSIGHT_VARIABLE_TYPE_TO_OPENAPI: dict[str, dict] = {
    InsightVariable.Type.STRING: {"type": "string"},
    InsightVariable.Type.NUMBER: {"type": "number"},
    InsightVariable.Type.BOOLEAN: {"type": "boolean"},
    InsightVariable.Type.LIST: {"type": "array", "items": {"type": "string"}},
    InsightVariable.Type.DATE: {"type": "string", "format": "date"},
}


def generate_openapi_spec(
    endpoint: Endpoint, team_id: int, request: Request, version: EndpointVersion | None = None
) -> dict:
    """Generate OpenAPI 3.0 spec for a single endpoint.

    Args:
        endpoint: The endpoint to generate spec for
        team_id: The team ID
        request: The HTTP request
        version: Specific version to generate spec for. If None, uses current version.
    """
    base_url = settings.SITE_URL
    run_path = f"/api/projects/{team_id}/endpoints/{endpoint.name}/run"
    target_version = version or endpoint.get_version()
    description = target_version.description

    schemas = _build_component_schemas(endpoint, target_version, team_id)
    variables_required = bool(schemas.get("Variables", {}).get("required"))
    if variables_required:
        # The Variables schema's `required` array only fires once the caller
        # actually includes a `variables` key. Make `variables` itself
        # required on EndpointRunRequest too, otherwise an SDK client that
        # POSTs `{}` passes validation.
        schemas["EndpointRunRequest"].setdefault("required", []).append("variables")

    return {
        "openapi": "3.0.3",
        "info": {
            "title": endpoint.name,
            "description": description or f"PostHog Endpoint: {endpoint.name}",
            "version": str(target_version.version),
        },
        "servers": [{"url": base_url}],
        "paths": {
            run_path: {
                "post": {
                    "operationId": f"run_{endpoint.name.replace('-', '_')}",
                    "summary": f"Execute {endpoint.name}",
                    "description": description or f"Execute the {endpoint.name} endpoint",
                    "security": [{"PersonalAPIKey": []}],
                    "requestBody": {
                        "required": variables_required,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/EndpointRunRequest"},
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Query results",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "results": {
                                                "type": "array",
                                                "items": {},
                                                "description": "Query result rows",
                                            },
                                            "columns": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "Column names (for HogQL queries)",
                                            },
                                            "hasMore": {
                                                "type": "boolean",
                                                "description": "Whether there are more results available",
                                            },
                                        },
                                        "required": ["results"],
                                    }
                                }
                            },
                        },
                        "400": {
                            "description": (
                                "Invalid request, or the query is too expensive to run inline. "
                                "Query-cost failures carry a stable `code`: `query_timeout`, "
                                "`query_memory_limit`, `query_too_large`, or `query_estimated_too_slow` — "
                                "narrow the query's scope (e.g. a smaller date range) or materialize the endpoint."
                            ),
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                        },
                        "401": {"description": "Authentication required"},
                        "404": {"description": "Endpoint not found"},
                        "503": {
                            "description": (
                                "The shared ClickHouse query pool is momentarily at capacity (`code`: "
                                "`query_capacity`). Retry shortly; materialize the endpoint to run on dedicated "
                                "compute that isn't affected by shared query load."
                            ),
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                        },
                    },
                }
            }
        },
        "components": {
            "securitySchemes": {
                "PersonalAPIKey": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Personal API Key from PostHog. Get one at /settings/user-api-keys",
                }
            },
            "schemas": schemas,
        },
    }


def _build_component_schemas(endpoint: Endpoint, version: EndpointVersion, team_id: int) -> dict:
    """Build the components/schemas section with reusable schema definitions."""
    query = version.query
    is_materialized = bool(version and version.is_materialized and version.saved_query)

    schemas: dict = {
        "Error": {
            "type": "object",
            "description": "Error response body.",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Coarse error category (e.g. 'validation_error', 'server_error'). Branch on `code`, not `type`.",
                },
                "code": {
                    "type": "string",
                    "description": "Stable machine-readable error code to branch on, e.g. 'query_timeout' or 'query_capacity'.",
                },
                "detail": {"type": "string", "description": "Human-readable explanation and remediation."},
                "attr": {
                    "type": "string",
                    "nullable": True,
                    "description": "The request field that caused the error, when applicable.",
                },
            },
            "required": ["type", "code", "detail"],
        },
        "EndpointRunRequest": {
            "type": "object",
            "properties": {
                "client_query_id": {
                    "type": "string",
                    "description": "Client provided query ID. Can be used to retrieve the status or cancel the query.",
                },
                "filters_override": {
                    "$ref": "#/components/schemas/DashboardFilter",
                },
                "refresh": {
                    "type": "string",
                    "enum": ["cache", "force", "direct"],
                    "default": "cache",
                    "description": (
                        "How to handle caching. "
                        "'cache' returns cached results if fresh enough. "
                        "'force' always recalculates. "
                        "'direct' bypasses materialization (materialized endpoints only)."
                    ),
                },
                "version": {
                    "type": "integer",
                    "description": f"Specific endpoint version to execute (1-{endpoint.current_version}). Defaults to latest.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (SQL-based endpoints only).",
                    "minimum": 1,
                },
                "debug": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to include debug information (such as the executed SQL) in the response.",
                },
            },
        },
        "DashboardFilter": {
            "type": "object",
            "description": "Override dashboard/query filters including date range and properties.",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start date for the query (e.g., '-7d', '2024-01-01', 'mStart').",
                    "examples": ["-7d", "-30d", "2024-01-01", "mStart"],
                },
                "date_to": {
                    "type": "string",
                    "description": "End date for the query (e.g., 'now', '2024-12-31'). Defaults to now.",
                    "examples": ["now", "2024-12-31", "dStart"],
                },
                "properties": {
                    "type": "array",
                    "description": "Property filters to apply to the query.",
                    "items": {"$ref": "#/components/schemas/PropertyFilter"},
                },
            },
        },
        "PropertyFilter": {
            "type": "object",
            "description": "A property filter to narrow down results.",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The property key to filter on.",
                },
                "value": {
                    "description": "The value(s) to filter for.",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "number"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "operator": {
                    "type": "string",
                    "enum": [
                        "exact",
                        "is_not",
                        "icontains",
                        "not_icontains",
                        "regex",
                        "not_regex",
                        "gt",
                        "lt",
                        "gte",
                        "lte",
                        "is_set",
                        "is_not_set",
                        "is_date_exact",
                        "is_date_before",
                        "is_date_after",
                        "in",
                        "not_in",
                    ],
                    "description": "The comparison operator.",
                },
                "type": {
                    "type": "string",
                    "enum": ["event", "person", "session", "cohort", "group", "hogql"],
                    "description": "The type of property filter.",
                },
            },
            "required": ["key"],
        },
    }

    # Add variables schema based on query type and materialization state
    variables_schema = _build_variables_schema(query, is_materialized, team_id, version)
    if variables_schema:
        schemas["EndpointRunRequest"]["properties"]["variables"] = {
            "$ref": "#/components/schemas/Variables",
        }
        schemas["Variables"] = variables_schema

    return schemas


def _build_variables_schema(
    query: dict, is_materialized: bool, team_id: int, version: EndpointVersion | None = None
) -> dict | None:
    """Build schema for variables based on query type and materialization state.

    Emits a top-level ``required`` array so generated SDKs and clients see which
    variables they MUST send to /run. For insight endpoints this respects
    ``EndpointVersion.optional_breakdown_properties`` — opted-out breakdowns are
    listed as properties but kept out of ``required``, matching the runtime check.
    """
    query_kind = query.get("kind")
    properties: dict = {}
    required: list[str] = []
    optional_breakdowns: set[str] = set(version.optional_breakdown_properties or []) if version is not None else set()

    if query_kind == "HogQLQuery":
        variables = query.get("variables", {})
        if variables:
            variable_ids = list(variables.keys())
            variable_types = {
                str(uid): vtype
                for uid, vtype in InsightVariable.objects.filter(team_id=team_id, id__in=variable_ids).values_list(
                    "id", "type"
                )
            }

            for var_id, var_data in variables.items():
                code_name = var_data.get("code_name", var_id)
                default_value = var_data.get("value")
                var_type = variable_types.get(var_id)
                type_schema = (
                    INSIGHT_VARIABLE_TYPE_TO_OPENAPI.get(var_type, {"type": "string"})
                    if var_type
                    else {"type": "string"}
                )
                properties[code_name] = {
                    **type_schema,
                    "description": f"Variable: {code_name}",
                }
                if default_value is not None:
                    properties[code_name]["example"] = default_value
                else:
                    required.append(code_name)
            # Materialized HogQL rejects ANY missing variable at run time, defaults included.
            if is_materialized:
                required = sorted(properties.keys())
    else:
        # Insight queries - only include breakdown for supported query types
        if query_kind in InsightEndpointStrategy.BREAKDOWN_SUPPORTED_QUERY_TYPES:
            breakdown_filter = query.get("breakdownFilter") or {}
            for breakdown in _breakdown_property_names(breakdown_filter):
                if breakdown in properties:
                    continue
                properties[breakdown] = {
                    "type": "string",
                    "description": f"Filter by {breakdown} breakdown value",
                    "example": "Chrome",
                }
                # Breakdown variables are enforced at run time on both inline and
                # materialized paths, unless the endpoint owner opted them out.
                if breakdown not in optional_breakdowns:
                    required.append(breakdown)

        if not is_materialized:
            # Non-materialized also supports date variables — never required.
            properties["date_from"] = {
                "type": "string",
                "description": "Filter results from this date (ISO format or relative like '-7d')",
                "example": "2024-01-01",
            }
            properties["date_to"] = {
                "type": "string",
                "description": "Filter results until this date (ISO format or relative like 'now')",
                "example": "2024-01-31",
            }

    if not properties:
        return None

    schema: dict = {
        "type": "object",
        "description": "Query variables. For HogQL: code_names from query. For insights: breakdown property and date_from/date_to.",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema
