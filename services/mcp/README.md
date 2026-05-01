# PostHog MCP

Documentation: https://posthog.com/docs/model-context-protocol

## Use the MCP Server

### Quick install

You can install the MCP server automatically into Cursor, Claude, Claude Code, VS Code and Zed by running the following command:

```bash
npx @posthog/wizard@latest mcp add
```

### Manual install

1. Obtain a personal API key using the [MCP Server preset](https://app.posthog.com/settings/user-api-keys?preset=mcp_server).

2. Add the MCP configuration to your desktop client (e.g. Cursor, Windsurf, Claude Desktop) and add your personal API key

```json
{
  "mcpServers": {
    "posthog": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@latest",
        "https://mcp.posthog.com/mcp",
        "--header",
        "Authorization:${POSTHOG_AUTH_HEADER}"
      ],
      "env": {
        "POSTHOG_AUTH_HEADER": "Bearer {INSERT_YOUR_PERSONAL_API_KEY_HERE}"
      }
    }
  }
}
```

### Minimal Node client (Streamable HTTP)

If you want to call MCP from Node (outside an IDE), use the Model Context Protocol SDK’s **Streamable HTTP** transport.

- **Auth:** Use a **personal** PostHog API key and pass it as a Bearer token in `Authorization`.
- **Accept header:** Clients **must** include `Accept: application/json, text/event-stream`.
- **Lifecycle:** MCP requires `initialize` then a client `notifications/initialized`; the SDK performs this during `connect()`.

```js
// tools-list.mjs
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import { ListToolsResultSchema } from '@modelcontextprotocol/sdk/types.js'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { URL } from 'node:url'

const AUTH = process.env.POSTHOG_AUTH_HEADER // "Bearer phx_…"
const MCP_URL = process.env.MCP_URL || 'https://mcp.posthog.com/mcp'

if (!AUTH?.startsWith('Bearer ')) {
  console.error('Set POSTHOG_AUTH_HEADER="Bearer phx_..."')
  process.exit(1)
}

const transport = new StreamableHTTPClientTransport(new URL(MCP_URL), {
  requestInit: {
    headers: {
      Authorization: AUTH,
      // Required for Streamable HTTP (JSON + SSE)
      Accept: 'application/json, text/event-stream',
    },
  },
  serverInfo: { name: 'example-node-client', version: '0.0.1' },
})

const client = new Client({ name: 'example-node-client', version: '0.0.1' })

// Handles initialize + notifications/initialized
await client.connect(transport)

const toolsResp = await client.request({ method: 'tools/list' }, ListToolsResultSchema) // { tools: [...] }
const tools = toolsResp?.tools ?? []
console.log('Tools:', tools.length)

// (Optional) Save the full JSON-RPC envelope to a file (run from repo root)
const envelope = { jsonrpc: '2.0', id: 'list-1', result: toolsResp }
mkdirSync('reports', { recursive: true })
writeFileSync(join('reports', 'tools-list-http.json'), JSON.stringify(envelope, null, 2))
console.log('Saved: reports/tools-list-http.json')

await client.close()
```

**Why these headers & steps?**

- Streamable HTTP requires the `Accept` header to include **both** JSON and SSE.
- After `initialize`, the client must send `notifications/initialized`; the SDK does this for you in `connect()`.

See also the main PostHog MCP docs for available tools and setup flows: [https://posthog.com/docs/model-context-protocol](https://posthog.com/docs/model-context-protocol)

### Docker install

If you prefer to use Docker instead of running npx directly:

1. Build the Docker image:

```bash
pnpm docker:build
# or
docker build -t posthog-mcp .
```

2. Configure your MCP client with Docker:

```json
{
  "mcpServers": {
    "posthog": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "--env",
        "POSTHOG_AUTH_HEADER=${POSTHOG_AUTH_HEADER}",
        "--env",
        "POSTHOG_REMOTE_MCP_URL=${POSTHOG_REMOTE_MCP_URL:-https://mcp.posthog.com/mcp}",
        "posthog-mcp"
      ],
      "env": {
        "POSTHOG_AUTH_HEADER": "Bearer {INSERT_YOUR_PERSONAL_API_KEY_HERE}",
        "POSTHOG_REMOTE_MCP_URL": "https://mcp.posthog.com/mcp"
      }
    }
  }
}
```

3. Test Docker with MCP Inspector:

```bash
pnpm docker:inspector
# or
npx @modelcontextprotocol/inspector docker run -i --rm --env POSTHOG_AUTH_HEADER=${POSTHOG_AUTH_HEADER} posthog-mcp
```

**Environment Variables:**

- `POSTHOG_AUTH_HEADER`: Your PostHog API token (required)
- `POSTHOG_REMOTE_MCP_URL`: The MCP server URL (optional, defaults to `https://mcp.posthog.com/mcp`)

This approach allows you to use the PostHog MCP server without needing Node.js or npm installed locally.

### Example Prompts

Below are detailed examples showing realistic prompts and expected outputs:

#### Example 1: Feature flag management

**Prompt:** "Create a feature flag called 'new-checkout-flow' that's enabled for 20% of users, and show me the configuration"

**What happens:**

1. The `create-feature-flag` tool creates the flag with a 20% rollout
2. Returns the flag configuration including the key, rollout percentage, and targeting rules

**Expected output:**

```text
Created feature flag 'new-checkout-flow':
- Key: new-checkout-flow
- Active: true
- Rollout: 20% of all users
- URL: https://app.posthog.com/feature_flags/12345
```

#### Example 2: Analytics query

**Prompt:** "How many unique users signed up in the last 7 days, broken down by day?"

**What happens:**

1. The `query-run` tool executes a trends query filtering for `$signup` events
2. Returns daily counts with unique user aggregation

**Expected output:**

```text
Signups over the last 7 days:

| Date       | Unique users |
|------------|--------------|
| 2025-01-17 | 142          |
| 2025-01-18 | 156          |
| 2025-01-19 | 98           |
| ...        | ...          |

Total: 847 unique signups
```

#### Example 3: A/B test creation and monitoring

**Prompt:** "Create an A/B test for our pricing page that measures conversion to the checkout page"

**What happens:**

1. The `experiment-create` tool creates an experiment with control/test variants
2. Sets up a funnel metric: pricing page view → checkout page view
3. Creates an associated feature flag for variant assignment

**Expected output:**

```text
Created experiment 'Pricing page test':
- Feature flag: pricing-page-test
- Variants: control (50%), test (50%)
- Primary metric: Funnel conversion (pricing_page → checkout)
- Status: Draft (ready to launch)
- URL: https://app.posthog.com/experiments/789
```

#### Example 4: Error investigation

**Prompt:** "What are the top 5 errors in my project this week and how many users are affected?"

**What happens:**

1. The `query-error-tracking-issues` tool fetches error groups sorted by occurrence count
2. Returns error details including affected user counts

**Expected output:**

```text
Top 5 errors this week:

1. TypeError: Cannot read property 'id' of undefined
   - Occurrences: 1,247
   - Users affected: 89
   - First seen: 2 days ago

2. NetworkError: Failed to fetch
   - Occurrences: 856
   - Users affected: 234
   - First seen: 5 days ago
...
```

#### Quick prompts

For simpler queries, you can use shorter prompts:

- "What feature flags do I have active?"
- "Show me my LLM costs this week"
- "List my dashboards"
- "What events are being tracked?"

### Feature Filtering

You can limit which tools are available by adding query parameters to the MCP URL. If no features are specified, all tools are available. When features are specified, only tools matching those features are exposed.

```text
https://mcp.posthog.com/mcp?features=flags,workspace,dashboards
```

Available features:

| Feature                  | Description                                                                                               |
| ------------------------ | --------------------------------------------------------------------------------------------------------- |
| `workspace`              | Organization and project management                                                                       |
| `actions`                | [Action definitions](https://posthog.com/docs/data/actions)                                               |
| `activity_logs`          | Activity log viewing                                                                                      |
| `alerts`                 | [Alert management](https://posthog.com/docs/product-analytics/alerts)                                     |
| `annotations`            | [Annotation management](https://posthog.com/docs/product-analytics/annotations)                           |
| `cohorts`                | [Cohort management](https://posthog.com/docs/data/cohorts)                                                |
| `dashboards`             | [Dashboard creation and management](https://posthog.com/docs/product-analytics/dashboards)                |
| `data_schema`            | Data schema exploration                                                                                   |
| `data_warehouse`         | [Data warehouse management](https://posthog.com/docs/data-warehouse)                                      |
| `debug`                  | Debug and diagnostic tools                                                                                |
| `docs`                   | PostHog documentation search                                                                              |
| `early_access_features`  | [Early access feature management](https://posthog.com/docs/feature-flags/early-access-feature-management) |
| `error_tracking`         | [Error monitoring and debugging](https://posthog.com/docs/error-tracking)                                 |
| `events`                 | Event and property definitions                                                                            |
| `experiments`            | [A/B testing experiments](https://posthog.com/docs/experiments)                                           |
| `flags`                  | [Feature flag management](https://posthog.com/docs/feature-flags)                                         |
| `hog_functions`          | [CDP function management](https://posthog.com/docs/cdp)                                                   |
| `hog_function_templates` | CDP function template browsing                                                                            |
| `insights`               | [Analytics insights](https://posthog.com/docs/product-analytics/insights)                                 |
| `llm_analytics`          | [LLM analytics evaluations](https://posthog.com/docs/ai-engineering)                                      |
| `prompts`                | [LLM prompt management](https://posthog.com/docs/ai-engineering)                                          |
| `logs`                   | [Log querying](https://posthog.com/docs/ai-engineering/observability)                                     |
| `notebooks`              | [Notebook management](https://posthog.com/docs/notebooks)                                                 |
| `persons`                | [Person and group management](https://posthog.com/docs/data/persons)                                      |
| `reverse_proxy`          | Reverse proxy record management                                                                           |
| `search`                 | Entity search across the project                                                                          |
| `sql`                    | SQL query execution                                                                                       |
| `surveys`                | [Survey management](https://posthog.com/docs/surveys)                                                     |
| `workflows`              | [Workflow management](https://posthog.com/docs/cdp)                                                       |

> **Note:** Hyphens and underscores are treated as equivalent in feature names (e.g., `error-tracking` and `error_tracking` both work).

To view which tools are available per feature, see our [documentation](https://posthog.com/docs/model-context-protocol) or check `schema/tool-definitions-all.json`.

### Tool filtering

For finer-grained control you can allowlist specific tools by name using the `tools` query parameter. Only the exact tool names listed will be exposed, regardless of their feature category.

```text
https://mcp.posthog.com/mcp?tools=dashboard-get,feature-flag-get-all,execute-sql
```

When `features` and `tools` are both provided they are combined as a **union** — a tool is included if it matches a feature category **or** is in the tools list. This lets you select a feature group and add a handful of individual tools on top:

```text
https://mcp.posthog.com/mcp?features=flags&tools=dashboard-get
```

The example above exposes all flag tools plus `dashboard-get`.

### Server mode (tools vs cli)

The MCP server can register either every PostHog tool individually (**tools** mode, the default for most clients) or wrap them all behind a single `posthog` CLI-like tool (**cli** mode, used for token-constrained coding agents). When the caller does not say which mode they want, the server picks one automatically based on the client (coding agents get the cli mode when the rollout flag is enabled).

You can pin the choice yourself with either a query parameter or a header. Only `tools` and `cli` are accepted:

```text
https://mcp.posthog.com/mcp?mode=cli
https://mcp.posthog.com/mcp?mode=tools
```

```http
x-posthog-mcp-mode: cli
x-posthog-mcp-mode: tools
```

| Value   | Behavior                                                |
| ------- | ------------------------------------------------------- |
| `tools` | Force tools mode (one MCP tool per PostHog tool).       |
| `cli`   | Force cli mode (single `posthog` tool wraps all tools). |

The header wins when both the header and the query parameter are set. Any other value is ignored and the auto-detection takes over.

### Consumer attribution

Wrapping apps and AI-tool plugins that install or proxy the PostHog MCP can self-identify so usage can be attributed to the install path (e.g. plugin-installed vs. manually-pasted URL). The wrapped MCP client (Claude Code, Cursor, …) is already captured separately via the MCP `clientInfo` handshake — this signal is only for the wrapping context.

```text
https://mcp.posthog.com/mcp?consumer=plugin
```

```http
x-posthog-mcp-consumer: plugin
```

The header wins when both the header and the query parameter are set. Reserved values: `plugin` (AI-tool plugin installs), `posthog-code` (PostHog Code Tasks sandbox), `slack` (Slack integration).

### Data processing

The MCP server is hosted on a Cloudflare worker which can be located outside of the EU / US, for this reason the MCP server does not store any sensitive data outside of your cloud region.

### Using self-hosted instances

If you're using a self-hosted instance of PostHog, you can specify a custom base URL by adding the `POSTHOG_BASE_URL` [environment variable](https://developers.cloudflare.com/workers/configuration/environment-variables) when running the MCP server locally or on your own infrastructure, e.g. `POSTHOG_BASE_URL=https://posthog.example.com`

# Development

To run the MCP server locally, run the following command:

```bash
pnpm run dev
```

And replace `https://mcp.posthog.com/mcp` with `http://localhost:8787/mcp` in the MCP configuration.

### Developing with local resources

To develop with warm loading for MCP resources (workflows, prompts, examples):

1. Start the [context-mill](https://github.com/PostHog/context-mill) dev server: `cd ../context-mill && npm run dev`
2. Start the MCP server with local resources: `pnpm run dev:local-resources`

Changes in the examples repo will be reflected on the next request.

## Project Structure

This repository is organized to support multiple language implementations:

- `typescript/` - TypeScript implementation of the MCP server & tools
- `schema/` - Shared schema files generated from TypeScript

### Development Commands

- `pnpm run dev` - Start development server
- `pnpm run schema:build:json` - Generate JSON schema for other language implementations
- `pnpm run lint && pnpm run format` - Format and lint code

### Adding New Tools

See the [tools documentation](typescript/src/tools/README.md) for a guide on adding new tools to the MCP server.

### Environment variables

- Create `.dev.vars` in the root
- Add Inkeep API key to enable `docs-search` tool (see `Inkeep API key - mcp`)

```bash
INKEEP_API_KEY="..."
```

### Configuring the Model Context Protocol Inspector

During development you can directly inspect the MCP tool call results using the [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector).

You can run it using the following command:

```bash
npx @modelcontextprotocol/inspector npx -y mcp-remote@latest http://localhost:8787/mcp --header "\"Authorization: Bearer {INSERT_YOUR_PERSONAL_API_KEY_HERE}\""
```

Alternatively, you can use the following configuration in the MCP Inspector:

Use transport type `STDIO`.

**Command:**

```bash
npx
```

**Arguments:**

```bash
-y mcp-remote@latest http://localhost:8787/mcp --header "Authorization: Bearer {INSERT_YOUR_PERSONAL_API_KEY_HERE}"
```

### Developing against Claude Desktop

Claude Desktop is one of the easiest ways to test MCP Apps - while PostHog Code doesn't support it. You can configure access Settings > Developer and then edit `claude_desktop_config.json` with the following:

```json
{
  "mcpServers": {
    "posthog-local": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "http://localhost:8787/mcp"]
    }
  }
}
```

## Privacy & Support

- **Privacy Policy:** https://posthog.com/privacy
- **Terms of Service:** https://posthog.com/terms
- **Support:** https://posthog.com/questions or email support@posthog.com
- **GitHub Issues:** https://github.com/PostHog/posthog/issues

### Data handling

The MCP server acts as a proxy to your PostHog instance. It does not store your analytics data - all queries are executed against your PostHog project and results are returned directly to your AI client. Session state (active project/organization) is cached temporarily using Cloudflare Durable Objects tied to your API key hash.

For EU users, use the `mcp-eu.posthog.com` endpoint to ensure OAuth flows route to the EU PostHog instance.
