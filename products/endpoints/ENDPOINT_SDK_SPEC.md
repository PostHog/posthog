# Endpoint SDK Generation - Technical Specification

## Overview

Generate typed SDK clients from PostHog endpoints. Developers run a CLI command and get a production-ready, typed client for their endpoint in their language of choice.

```bash
posthog endpoints sdk my-endpoint --lang typescript --output ./src/posthog/
```

## Goals

1. **Zero configuration**: Works out of the box with just endpoint name
2. **Fully typed**: Variables, return columns, errors - all typed
3. **Minimal output**: Clean, readable code - not bloated generator output
4. **Multiple languages**: TypeScript, Python, Go (start with TS)
5. **Stays in sync**: Easy to regenerate when endpoint changes

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  CLI (posthog-cli)                                              │
│  $ posthog endpoints sdk my-endpoint --lang typescript          │
│                                                                 │
│  1. Reads ~/.posthog/config for API key + host                  │
│  2. Calls GET /api/endpoints/{name}/sdk?lang=typescript         │
│  3. Writes returned files to --output directory                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostHog API                                                    │
│  GET /api/environments/{team_id}/endpoints/{name}/sdk           │
│                                                                 │
│  1. Load endpoint definition (query, variables)                 │
│  2. Infer return schema (parse HogQL or dry-run query)          │
│  3. Generate SDK code from templates                            │
│  4. Return as JSON { files: { "client.ts": "...", ... } }       │
└─────────────────────────────────────────────────────────────────┘
```

## API Endpoint

### `GET /api/environments/{team_id}/endpoints/{name}/sdk`

**Query Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `lang` | string | Yes | Target language: `typescript`, `python`, `go` |
| `package_name` | string | No | Package/module name (default: endpoint name) |
| `include_base_client` | bool | No | Include base PostHog client code (default: false) |

**Response:**
```json
{
  "files": {
    "my-endpoint.ts": "export class MyEndpoint { ... }",
    "types.ts": "export interface MyEndpointRow { ... }"
  },
  "metadata": {
    "endpoint_name": "my-endpoint",
    "endpoint_version": 3,
    "generated_at": "2024-01-15T10:30:00Z",
    "lang": "typescript",
    "posthog_host": "https://us.posthog.com"
  }
}
```

**Errors:**
- `404`: Endpoint not found
- `400`: Unsupported language
- `500`: Schema inference failed (query parse error)

## Schema Inference

We need to determine the return type of the endpoint's query. Two approaches:

### Approach A: Parse HogQL AST (Preferred)

Use existing HogQL parser to extract SELECT columns and their types.

```python
# products/endpoints/backend/sdk/schema_inference.py

from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types

def infer_return_schema(query: str, team: Team) -> list[ColumnSchema]:
    """
    Parse HogQL query and extract column names + types.

    Returns:
        [
            {"name": "date", "type": "Date", "nullable": False},
            {"name": "users", "type": "UInt64", "nullable": False},
            {"name": "revenue", "type": "Float64", "nullable": True},
        ]
    """
    ast = parse_select(query)
    resolved = resolve_types(ast, team)

    columns = []
    for expr in resolved.select:
        col_name = expr.alias or _infer_column_name(expr)
        col_type = _get_clickhouse_type(expr.type)
        columns.append({
            "name": col_name,
            "type": col_type,
            "nullable": _is_nullable(expr.type)
        })

    return columns
```

### Approach B: Dry-run Query (Fallback)

Execute query with `LIMIT 0` and inspect result metadata.

```python
def infer_return_schema_via_dryrun(query: str, team: Team) -> list[ColumnSchema]:
    """
    Execute query with LIMIT 0 to get column metadata.
    More reliable but slower.
    """
    result = execute_hogql_query(
        query=f"SELECT * FROM ({query}) LIMIT 0",
        team=team
    )
    return result.columns  # ClickHouse returns column metadata
```

## Type Mapping

### ClickHouse → TypeScript

```python
CH_TO_TYPESCRIPT = {
    # Integers
    "UInt8": "number",
    "UInt16": "number",
    "UInt32": "number",
    "UInt64": "number",
    "Int8": "number",
    "Int16": "number",
    "Int32": "number",
    "Int64": "number",

    # Floats
    "Float32": "number",
    "Float64": "number",

    # Strings
    "String": "string",
    "FixedString": "string",
    "UUID": "string",

    # Dates/Times
    "Date": "string",      # ISO date string
    "DateTime": "string",  # ISO datetime string
    "DateTime64": "string",

    # Boolean
    "Bool": "boolean",
    "UInt8": "boolean",  # Context-dependent, see below

    # Complex
    "Array(String)": "string[]",
    "Array(UInt64)": "number[]",
    "Map(String, String)": "Record<string, string>",
    "Nullable(String)": "string | null",

    # JSON
    "JSON": "Record<string, unknown>",
}
```

### ClickHouse → Python

```python
CH_TO_PYTHON = {
    "UInt8": "int",
    "UInt64": "int",
    "Float64": "float",
    "String": "str",
    "Date": "datetime.date",
    "DateTime": "datetime.datetime",
    "Bool": "bool",
    "Array(String)": "list[str]",
    "Nullable(String)": "str | None",
    "JSON": "dict[str, Any]",
}
```

## Variable Schema Extraction

Extract variable definitions from the endpoint:

```python
def extract_variables(endpoint: Endpoint) -> list[VariableSchema]:
    """
    Extract variables from endpoint query.

    Query: SELECT * FROM events WHERE date > {variables.date_from}
    Variables config: {"date_from": {"type": "String", "default": "2024-01-01"}}

    Returns:
        [
            {
                "name": "date_from",
                "type": "string",
                "required": False,
                "default": "2024-01-01",
                "description": None
            }
        ]
    """
    query_variables = endpoint.query.get("variables", {})

    variables = []
    for var_id, var_config in query_variables.items():
        variables.append({
            "name": var_config.get("code_name", var_id),
            "type": _map_variable_type(var_config.get("type")),
            "required": var_config.get("required", False),
            "default": var_config.get("value"),
            "description": var_config.get("description"),
        })

    return variables
```

## SDK Templates

### TypeScript Template

```python
TYPESCRIPT_TEMPLATE = '''
// Auto-generated by PostHog Endpoints SDK
// Endpoint: {{ endpoint_name }} (v{{ endpoint_version }})
// Generated: {{ generated_at }}
// Do not edit manually - regenerate with: posthog endpoints sdk {{ endpoint_name }} --lang typescript

{% if variables %}
export interface {{ class_name }}Variables {
{% for var in variables %}
  /** {{ var.description or '' }} */
  {{ var.name }}{% if not var.required %}?{% endif %}: {{ var.ts_type }}{% if var.default %} // default: {{ var.default | tojson }}{% endif %}

{% endfor %}
}
{% endif %}

export interface {{ class_name }}Row {
{% for col in columns %}
  {{ col.name }}: {{ col.ts_type }}{% if col.nullable %} | null{% endif %}

{% endfor %}
}

export interface {{ class_name }}Response {
  results: {{ class_name }}Row[]
  is_cached: boolean
  last_refresh: string | null
  endpoint_version: number
}

export type EndpointRefreshMode = 'cache' | 'fresh' | 'live'

export interface {{ class_name }}Options {
{% if variables %}
  variables?: {{ class_name }}Variables
{% endif %}
  refresh?: EndpointRefreshMode
  filters_override?: Record<string, unknown>
}

export class {{ class_name }} {
  private apiKey: string
  private host: string

  constructor(options: { apiKey: string; host?: string }) {
    this.apiKey = options.apiKey
    this.host = options.host || '{{ posthog_host }}'
  }

  async run(options?: {{ class_name }}Options): Promise<{{ class_name }}Response> {
    const response = await fetch(
      `${this.host}/api/environments/{{ team_id }}/endpoints/{{ endpoint_name }}/run`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          variables: options?.variables,
          refresh: options?.refresh,
          filters_override: options?.filters_override,
        }),
      }
    )

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || `Request failed: ${response.status}`)
    }

    return response.json()
  }
}

// Convenience function for one-off usage
export async function run{{ class_name }}(
  apiKey: string,
  options?: {{ class_name }}Options & { host?: string }
): Promise<{{ class_name }}Response> {
  const client = new {{ class_name }}({ apiKey, host: options?.host })
  return client.run(options)
}
'''
```

### Python Template

```python
PYTHON_TEMPLATE = '''
"""
Auto-generated by PostHog Endpoints SDK
Endpoint: {{ endpoint_name }} (v{{ endpoint_version }})
Generated: {{ generated_at }}
Do not edit manually - regenerate with: posthog endpoints sdk {{ endpoint_name }} --lang python
"""

from __future__ import annotations

import httpx
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
{% if has_optional_vars %}
from typing import Optional
{% endif %}


{% if variables %}
@dataclass
class {{ class_name }}Variables:
{% for var in variables %}
    {{ var.name }}: {{ var.py_type }}{% if not var.required %} = {{ var.default | python_default }}{% endif %}
{% if var.description %}
    """{{ var.description }}"""
{% endif %}
{% endfor %}
{% endif %}


@dataclass
class {{ class_name }}Row:
{% for col in columns %}
    {{ col.name }}: {{ col.py_type }}
{% endfor %}


@dataclass
class {{ class_name }}Response:
    results: list[{{ class_name }}Row]
    is_cached: bool
    last_refresh: str | None
    endpoint_version: int


EndpointRefreshMode = Literal["cache", "fresh", "live"]


class {{ class_name }}:
    def __init__(
        self,
        api_key: str,
        host: str = "{{ posthog_host }}",
    ):
        self.api_key = api_key
        self.host = host
        self._client = httpx.Client(
            base_url=host,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def run(
        self,
{% if variables %}
        variables: {{ class_name }}Variables | None = None,
{% endif %}
        refresh: EndpointRefreshMode = "cache",
        filters_override: dict[str, Any] | None = None,
    ) -> {{ class_name }}Response:
        response = self._client.post(
            "/api/environments/{{ team_id }}/endpoints/{{ endpoint_name }}/run",
            json={
{% if variables %}
                "variables": vars(variables) if variables else None,
{% endif %}
                "refresh": refresh,
                "filters_override": filters_override,
            },
        )
        response.raise_for_status()
        data = response.json()

        return {{ class_name }}Response(
            results=[{{ class_name }}Row(**row) for row in data["results"]],
            is_cached=data.get("is_cached", False),
            last_refresh=data.get("last_refresh"),
            endpoint_version=data.get("endpoint_version", 1),
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()
'''
```

## Implementation

### File Structure

```
products/endpoints/backend/
├── sdk/
│   ├── __init__.py
│   ├── generator.py          # Main SDK generation logic
│   ├── schema_inference.py   # HogQL → column types
│   ├── type_mapping.py       # CH types → language types
│   └── templates/
│       ├── typescript.py     # TS template
│       ├── python.py         # Python template
│       └── go.py             # Go template (future)
└── api.py                    # Add /sdk endpoint
```

### Core Generator

```python
# products/endpoints/backend/sdk/generator.py

from dataclasses import dataclass
from jinja2 import Template

from .schema_inference import infer_return_schema, extract_variables
from .type_mapping import map_types_for_language
from .templates import TEMPLATES


@dataclass
class GeneratedSDK:
    files: dict[str, str]
    metadata: dict


def generate_sdk(
    endpoint: Endpoint,
    team: Team,
    lang: str,
    package_name: str | None = None,
) -> GeneratedSDK:
    """
    Generate SDK files for an endpoint.
    """
    if lang not in TEMPLATES:
        raise ValueError(f"Unsupported language: {lang}")

    # 1. Infer return schema from query
    columns = infer_return_schema(endpoint.query, team)

    # 2. Extract variables
    variables = extract_variables(endpoint)

    # 3. Map types to target language
    columns = map_types_for_language(columns, lang)
    variables = map_types_for_language(variables, lang)

    # 4. Generate class name from endpoint name
    class_name = _to_class_name(endpoint.name)  # my-endpoint → MyEndpoint

    # 5. Render template
    template = Template(TEMPLATES[lang])
    code = template.render(
        endpoint_name=endpoint.name,
        endpoint_version=endpoint.current_version,
        class_name=class_name,
        columns=columns,
        variables=variables,
        team_id=team.id,
        posthog_host=settings.SITE_URL,
        generated_at=datetime.now(UTC).isoformat(),
        has_optional_vars=any(not v.get("required") for v in variables),
    )

    # 6. Determine output filename
    filename = _get_filename(endpoint.name, lang)

    return GeneratedSDK(
        files={filename: code},
        metadata={
            "endpoint_name": endpoint.name,
            "endpoint_version": endpoint.current_version,
            "generated_at": datetime.now(UTC).isoformat(),
            "lang": lang,
            "posthog_host": settings.SITE_URL,
        }
    )


def _to_class_name(endpoint_name: str) -> str:
    """Convert endpoint name to PascalCase class name."""
    # my-endpoint → MyEndpoint
    # daily_active_users → DailyActiveUsers
    words = endpoint_name.replace("-", "_").split("_")
    return "".join(word.capitalize() for word in words)


def _get_filename(endpoint_name: str, lang: str) -> str:
    """Get appropriate filename for language."""
    safe_name = endpoint_name.replace("-", "_")
    extensions = {
        "typescript": ".ts",
        "python": ".py",
        "go": ".go",
    }
    return f"{safe_name}{extensions[lang]}"
```

### API Endpoint

```python
# Add to products/endpoints/backend/api.py

from products.endpoints.backend.sdk.generator import generate_sdk

class EndpointViewSet(...):

    @extend_schema(
        description="Generate a typed SDK client for this endpoint.",
        parameters=[
            OpenApiParameter("lang", str, required=True, enum=["typescript", "python"]),
            OpenApiParameter("package_name", str, required=False),
        ],
    )
    @action(methods=["GET"], detail=True, url_path="sdk")
    def sdk(self, request: Request, name=None, *args, **kwargs) -> Response:
        """Generate SDK for this endpoint."""
        endpoint = get_object_or_404(Endpoint, team=self.team, name=name)

        lang = request.query_params.get("lang")
        if not lang:
            raise ValidationError("'lang' query parameter is required")

        if lang not in ["typescript", "python"]:
            raise ValidationError(f"Unsupported language: {lang}")

        package_name = request.query_params.get("package_name")

        try:
            sdk = generate_sdk(
                endpoint=endpoint,
                team=self.team,
                lang=lang,
                package_name=package_name,
            )
        except Exception as e:
            capture_exception(e)
            raise ValidationError(f"Failed to generate SDK: {str(e)}")

        return Response({
            "files": sdk.files,
            "metadata": sdk.metadata,
        })
```

## CLI Integration

The CLI is separate from this spec, but here's how it would call the API:

```bash
# ~/.posthog/config
api_key = "phx_..."
host = "https://us.posthog.com"

# Usage
$ posthog endpoints sdk my-endpoint --lang typescript --output ./src/posthog/

# What it does:
# 1. Read config
# 2. GET /api/environments/{team_id}/endpoints/my-endpoint/sdk?lang=typescript
# 3. Write response.files to ./src/posthog/
# 4. Print success message

Generating SDK for 'my-endpoint'...
✓ Created ./src/posthog/my_endpoint.ts

Usage:
  import { MyEndpoint } from './posthog/my_endpoint'

  const client = new MyEndpoint({ apiKey: process.env.POSTHOG_API_KEY })
  const data = await client.run({ variables: { date_from: '2024-01-01' } })
```

## Example Output

Given this endpoint:

```yaml
name: daily-active-users
query: |
  SELECT
    toDate(timestamp) as date,
    uniq(distinct_id) as users,
    sum(toFloat64(properties.$value)) as revenue
  FROM events
  WHERE event = {variables.event_name}
    AND timestamp >= {variables.date_from}
  GROUP BY date
  ORDER BY date DESC
variables:
  event_name:
    code_name: event_name
    type: String
    value: "$pageview"
  date_from:
    code_name: date_from
    type: String
    required: true
```

Generated TypeScript:

```typescript
// Auto-generated by PostHog Endpoints SDK
// Endpoint: daily-active-users (v1)
// Generated: 2024-01-15T10:30:00Z
// Do not edit manually - regenerate with: posthog endpoints sdk daily-active-users --lang typescript

export interface DailyActiveUsersVariables {
  /** Event to track as "active" */
  event_name?: string // default: "$pageview"
  date_from: string
}

export interface DailyActiveUsersRow {
  date: string
  users: number
  revenue: number | null
}

export interface DailyActiveUsersResponse {
  results: DailyActiveUsersRow[]
  is_cached: boolean
  last_refresh: string | null
  endpoint_version: number
}

export type EndpointRefreshMode = 'cache' | 'fresh' | 'live'

export interface DailyActiveUsersOptions {
  variables?: DailyActiveUsersVariables
  refresh?: EndpointRefreshMode
  filters_override?: Record<string, unknown>
}

export class DailyActiveUsers {
  private apiKey: string
  private host: string

  constructor(options: { apiKey: string; host?: string }) {
    this.apiKey = options.apiKey
    this.host = options.host || 'https://us.posthog.com'
  }

  async run(options?: DailyActiveUsersOptions): Promise<DailyActiveUsersResponse> {
    const response = await fetch(
      `${this.host}/api/environments/12345/endpoints/daily-active-users/run`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          variables: options?.variables,
          refresh: options?.refresh,
          filters_override: options?.filters_override,
        }),
      }
    )

    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || `Request failed: ${response.status}`)
    }

    return response.json()
  }
}

export async function runDailyActiveUsers(
  apiKey: string,
  options?: DailyActiveUsersOptions & { host?: string }
): Promise<DailyActiveUsersResponse> {
  const client = new DailyActiveUsers({ apiKey, host: options?.host })
  return client.run(options)
}
```

## Testing

```python
# products/endpoints/backend/sdk/tests/test_generator.py

class TestSDKGeneration:

    def test_generates_typescript_sdk(self, endpoint, team):
        sdk = generate_sdk(endpoint, team, "typescript")

        assert "daily_active_users.ts" in sdk.files
        code = sdk.files["daily_active_users.ts"]

        assert "export class DailyActiveUsers" in code
        assert "export interface DailyActiveUsersRow" in code
        assert "date: string" in code
        assert "users: number" in code

    def test_infers_column_types(self, team):
        query = "SELECT toDate(timestamp) as d, count() as c FROM events"
        columns = infer_return_schema(query, team)

        assert columns[0]["name"] == "d"
        assert columns[0]["type"] == "Date"
        assert columns[1]["name"] == "c"
        assert columns[1]["type"] == "UInt64"

    def test_handles_nullable_columns(self, team):
        query = "SELECT sumIf(1, event='x') as maybe_null FROM events"
        columns = infer_return_schema(query, team)

        assert columns[0]["nullable"] == True

    def test_extracts_variables(self, endpoint):
        variables = extract_variables(endpoint)

        assert len(variables) == 2
        assert variables[0]["name"] == "event_name"
        assert variables[0]["required"] == False
        assert variables[1]["name"] == "date_from"
        assert variables[1]["required"] == True
```

## Future Enhancements

1. **Watch mode**: `posthog endpoints sdk my-endpoint --watch` regenerates on endpoint changes
2. **Monorepo support**: Generate SDKs for all endpoints at once
3. **Validation schemas**: Generate Zod/Pydantic schemas for runtime validation
4. **React hooks**: `useEndpoint('daily-active-users')` with SWR/React Query integration
5. **OpenAPI passthrough**: Option to just return enhanced OpenAPI spec for custom generators
6. **Versioned SDKs**: Pin SDK to specific endpoint version

## Open Questions

1. Should we generate async Python client by default (httpx) or sync (requests)?
2. How to handle endpoints with Insight queries vs HogQL queries differently?
3. Should variables with defaults be optional in the SDK, or always required?
4. How to handle breaking changes when endpoint schema changes?
