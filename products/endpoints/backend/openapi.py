from django.conf import settings

from rest_framework.request import Request

from products.endpoints.backend.models import Endpoint, EndpointVersion


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
    run_path = f"/api/environments/{team_id}/endpoints/{endpoint.name}/run"
    target_version = version or endpoint.get_version()
    description = target_version.description

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
                        "required": False,
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
                        "400": {"description": "Invalid request"},
                        "401": {"description": "Authentication required"},
                        "404": {"description": "Endpoint not found"},
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
            "schemas": _build_component_schemas(endpoint, target_version),
        },
    }


def _build_component_schemas(endpoint: Endpoint, version: EndpointVersion) -> dict:
    """Build the components/schemas section with reusable schema definitions."""
    query = version.query
    is_materialized = bool(version and version.is_materialized and version.saved_query)

    schemas: dict = {
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
                    "enum": ["blocking", "force_blocking"],
                    "default": "blocking",
                    "description": (
                        "Whether results should be calculated sync or async. "
                        "'blocking' returns when done unless fresh cache exists. "
                        "'force_blocking' always calculates fresh."
                    ),
                },
                "version": {
                    "type": "integer",
                    "description": f"Specific endpoint version to execute (1-{endpoint.current_version}). Defaults to latest.",
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
    variables_schema = _build_variables_schema(query, is_materialized)
    if variables_schema:
        schemas["EndpointRunRequest"]["properties"]["variables"] = {
            "$ref": "#/components/schemas/Variables",
        }
        schemas["Variables"] = variables_schema

    return schemas


def _get_single_breakdown_property(breakdown_filter: dict) -> str | None:
    """Extract breakdown property from either legacy or new format."""
    breakdown = breakdown_filter.get("breakdown")
    if breakdown:
        return breakdown
    breakdowns = breakdown_filter.get("breakdowns") or []
    if len(breakdowns) == 1:
        return breakdowns[0].get("property")
    return None


# Query types that support user-configurable breakdown filtering
BREAKDOWN_SUPPORTED_QUERY_TYPES = {"TrendsQuery", "FunnelsQuery", "RetentionQuery"}


def _build_variables_schema(query: dict, is_materialized: bool) -> dict | None:
    """Build schema for variables based on query type and materialization state."""
    query_kind = query.get("kind")
    properties: dict = {}

    if query_kind == "HogQLQuery":
        # HogQL: variables from query definition
        variables = query.get("variables", {})
        for var_id, var_data in variables.items():
            code_name = var_data.get("code_name", var_id)
            default_value = var_data.get("value")
            properties[code_name] = {
                "type": "string",
                "description": f"Variable: {code_name}",
            }
            if default_value is not None:
                properties[code_name]["example"] = default_value
    else:
        # Insight queries - only include breakdown for supported query types
        if query_kind in BREAKDOWN_SUPPORTED_QUERY_TYPES:
            breakdown_filter = query.get("breakdownFilter") or {}
            breakdown = _get_single_breakdown_property(breakdown_filter)
            if breakdown:
                properties[breakdown] = {
                    "type": "string",
                    "description": f"Filter by {breakdown} breakdown value",
                    "example": "Chrome",
                }

        if not is_materialized:
            # Non-materialized also supports date variables
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

    return {
        "type": "object",
        "description": "Query variables. For HogQL: code_names from query. For insights: breakdown property and date_from/date_to.",
        "properties": properties,
        "additionalProperties": False,
    }
