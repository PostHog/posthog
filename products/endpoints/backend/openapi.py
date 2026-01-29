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
    query_kind = query.get("kind")

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

    # Add variables schema for HogQL queries
    if query_kind == "HogQLQuery":
        variables = query.get("variables")
        if variables:
            schemas["EndpointRunRequest"]["properties"]["variables"] = {
                "$ref": "#/components/schemas/Variables",
            }
            schemas["Variables"] = _build_variables_schema(variables)
    else:
        # Insight queries support query_override
        schemas["EndpointRunRequest"]["properties"]["query_override"] = {
            "type": "object",
            "description": "Override insight query parameters (e.g., series, dateRange, interval).",
            "additionalProperties": True,
        }

    return schemas


def _build_variables_schema(variables: dict) -> dict:
    """Build schema for HogQL variables based on the endpoint's defined variables."""
    properties = {}

    for var_id, var_data in variables.items():
        code_name = var_data.get("code_name", var_id)
        properties[code_name] = {
            "description": f"Variable: {code_name}",
        }

    return {
        "type": "object",
        "description": "HogQL query variables. Keys are variable code names as defined in the query.",
        "properties": properties,
        "additionalProperties": True,
    }
