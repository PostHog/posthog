from django.conf import settings

from rest_framework.request import Request

from posthog.schema import DashboardFilter, EndpointRunRequest

from products.endpoints.backend.models import Endpoint


def generate_openapi_spec(endpoint: Endpoint, team_id: int, request: Request) -> dict:
    """Generate OpenAPI 3.0 spec for a single endpoint."""
    base_url = settings.SITE_URL or f"{request.scheme}://{request.get_host()}"
    run_path = f"/api/environments/{team_id}/endpoints/{endpoint.name}/run"

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
            "schemas": _build_component_schemas(endpoint),
        },
    }


def _build_component_schemas(endpoint: Endpoint) -> dict:
    """Build the components/schemas section dynamically from Pydantic models."""
    # Generate JSON Schema from the actual Pydantic models
    request_schema = EndpointRunRequest.model_json_schema(mode="serialization")
    filter_schema = DashboardFilter.model_json_schema(mode="serialization")

    # Convert Pydantic's $defs to OpenAPI components/schemas format
    schemas = _convert_pydantic_schema(request_schema, "EndpointRunRequest")

    # Merge in DashboardFilter and its dependencies
    filter_schemas = _convert_pydantic_schema(filter_schema, "DashboardFilter")
    schemas.update(filter_schemas)

    # Add endpoint-specific customizations
    query_kind = endpoint.query.get("kind")
    if query_kind == "HogQLQuery":
        variables = endpoint.query.get("variables")
        if variables:
            schemas["EndpointRunRequest"]["properties"]["variables"] = {
                "$ref": "#/components/schemas/Variables",
            }
            schemas["Variables"] = _build_variables_schema(variables)

    return schemas


def _convert_pydantic_schema(pydantic_schema: dict, root_name: str) -> dict:
    """Convert Pydantic JSON Schema to OpenAPI components/schemas format.

    Pydantic generates schemas with $defs for nested types. OpenAPI uses
    components/schemas with $ref pointing to #/components/schemas/TypeName.
    """
    schemas = {}

    # Extract the root schema (without $defs)
    root_schema = {k: v for k, v in pydantic_schema.items() if k != "$defs"}

    # Fix $ref paths from #/$defs/X to #/components/schemas/X
    root_schema = _fix_refs(root_schema)
    schemas[root_name] = root_schema

    # Extract all $defs as separate schemas
    if "$defs" in pydantic_schema:
        for def_name, def_schema in pydantic_schema["$defs"].items():
            fixed_schema = _fix_refs(def_schema)
            schemas[def_name] = fixed_schema

    return schemas


def _fix_refs(schema: dict | list) -> dict | list:
    """Recursively fix $ref paths from Pydantic format to OpenAPI format."""
    if isinstance(schema, dict):
        result = {}
        for key, value in schema.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
                # Convert #/$defs/TypeName to #/components/schemas/TypeName
                type_name = value.replace("#/$defs/", "")
                result[key] = f"#/components/schemas/{type_name}"
            else:
                result[key] = _fix_refs(value)
        return result
    elif isinstance(schema, list):
        return [_fix_refs(item) for item in schema]
    else:
        return schema


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
