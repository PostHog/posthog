from django.conf import settings

from rest_framework.request import Request

from products.endpoints.backend.models import Endpoint


def generate_openapi_spec(endpoint: Endpoint, team_id: int, request: Request) -> dict:
    """Generate OpenAPI 3.0 spec for a single endpoint."""
    base_url = settings.SITE_URL or f"{request.scheme}://{request.get_host()}"
    run_path = f"/api/environments/{team_id}/endpoints/{endpoint.name}/run"

    request_schema = _build_request_schema(endpoint)

    return {
        "openapi": "3.0.3",
        "info": {
            "title": endpoint.name,
            "description": endpoint.description or f"PostHog Endpoint: {endpoint.name}",
            "version": str(endpoint.current_version),
        },
        "servers": [{"url": base_url}],
        "paths": {
            run_path: {
                "post": {
                    "operationId": f"run_{endpoint.name.replace('-', '_')}",
                    "summary": f"Execute {endpoint.name}",
                    "description": endpoint.description or f"Execute the {endpoint.name} endpoint",
                    "security": [{"PersonalAPIKey": []}],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": request_schema,
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
            }
        },
    }


def _build_request_schema(endpoint: Endpoint) -> dict:
    """Build the request body schema based on the endpoint's query type."""
    query_kind = endpoint.query.get("kind")
    properties: dict = {}
    schema: dict = {
        "type": "object",
        "properties": properties,
    }

    if query_kind == "HogQLQuery":
        variables = endpoint.query.get("variables")
        if variables:
            variables_schema = _build_variables_schema(variables)
            properties["variables"] = variables_schema
    else:
        properties["query_override"] = {
            "type": "object",
            "description": "Override query parameters (e.g., dateRange, interval)",
            "additionalProperties": True,
        }

    properties["filters_override"] = {
        "type": "object",
        "description": "Override dashboard filters",
        "properties": {
            "properties": {
                "type": "array",
                "items": {},
                "description": "Property filters to apply",
            }
        },
    }

    properties["refresh"] = {
        "type": "string",
        "enum": ["blocking", "force_blocking"],
        "default": "blocking",
        "description": "Refresh mode for the query",
    }

    properties["version"] = {
        "type": "integer",
        "description": f"Specific endpoint version to execute (1-{endpoint.current_version})",
    }

    return schema


def _build_variables_schema(variables: dict) -> dict:
    """Build schema for HogQL variables."""
    properties = {}

    for var_id, var_data in variables.items():
        code_name = var_data.get("code_name", var_id)
        properties[code_name] = {
            "description": f"Variable: {code_name}",
        }

    return {
        "type": "object",
        "description": "HogQL query variables",
        "properties": properties,
        "additionalProperties": True,
    }
