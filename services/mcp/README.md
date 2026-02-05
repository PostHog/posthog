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
        "https://mcp.posthog.com/mcp", // You can replace this with https://mcp.posthog.com/sse if your client does not support Streamable HTTP
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

1. The `list-errors` tool fetches error groups sorted by occurrence count
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

You can limit which tools are available by adding query parameters to the MCP URL:

```text
https://mcp.posthog.com/mcp?features=flags,workspace
```

Available features:

- `workspace` - Organization and project management
- `error-tracking` - [Error monitoring and debugging](https://posthog.com/docs/errors)
- `dashboards` - [Dashboard creation and management](https://posthog.com/docs/product-analytics/dashboards)
- `insights` - [Analytics insights and SQL queries](https://posthog.com/docs/product-analytics/insights)
- `experiments` - [A/B testing experiments](https://posthog.com/docs/experiments)
- `flags` - [Feature flag management](https://posthog.com/docs/feature-flags)
- `llm-analytics` - [LLM usage and cost tracking](https://posthog.com/docs/llm-analytics)
- `docs` - PostHog documentation search

To view which tools are available per feature, see our [documentation](https://posthog.com/docs/model-context-protocol) or alternatively check out `schema/tool-definitions.json`,

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

### Testing OAuth with external clients (v0, Cursor, etc.)

When an external service connects to your local MCP server via OAuth, requests are routed through public tunnels to your local PostHog instance. Django's dev server doesn't support HTTP chunked transfer encoding ([Django #35838](https://code.djangoproject.com/ticket/35838)), which some OAuth clients use for the token exchange. You need nginx as a reverse proxy to de-chunk these requests.

**Architecture:**

```text
External client → cloudflared tunnel → MCP server (:8787)
                → ngrok tunnel → nginx (:8080) → Django (:8000)
```

**Setup:**

1. **Ensure your PostHog `.env` has proxy settings** (needed so Django generates `https://` URLs):

   ```bash
   # In /path/to/posthog/.env
   IS_BEHIND_PROXY=True
   TRUST_ALL_PROXIES=True
   ```

2. **Start PostHog** as normal (`hogli start` or `python manage.py runserver 8000`)

3. **Install and start nginx** as a reverse proxy to de-chunk requests:

   ```bash
   brew install nginx
   ```

   Create a config file (e.g. `/tmp/nginx-dechunk.conf`):

   ```nginx
   worker_processes 1;
   error_log /tmp/nginx-dechunk-error.log;
   pid /tmp/nginx-dechunk.pid;

   events { worker_connections 64; }

   http {
       access_log /tmp/nginx-dechunk-access.log;
       server {
           listen 8080;
           location / {
               proxy_pass http://127.0.0.1:8000;
               proxy_http_version 1.1;
               proxy_set_header Host $http_host;
               proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
               proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
               proxy_set_header X-Forwarded-Host $http_x_forwarded_host;
           }
       }
   }
   ```

   ```bash
   /opt/homebrew/opt/nginx/bin/nginx -c /tmp/nginx-dechunk.conf
   ```

4. **Start tunnels:**

   ```bash
   # Tunnel for MCP server
   cloudflared tunnel --url http://localhost:8787

   # Tunnel for PostHog (point at nginx, NOT Django directly)
   ngrok http 8080
   ```

5. **Update `.dev.vars`** with the ngrok tunnel URL:

   ```bash
   POSTHOG_API_BASE_URL=https://your-ngrok-url.ngrok-free.dev
   POSTHOG_MCP_APPS_ANALYTICS_BASE_URL=https://your-ngrok-url.ngrok-free.dev
   ```

6. **Start the MCP server** (`pnpm run dev`) and connect your external client to the cloudflared URL (e.g. `https://xxx.trycloudflare.com/mcp`)

**Why nginx?** Some OAuth clients (e.g. Arctic, used by v0.app) send `Transfer-Encoding: chunked` POST requests during the token exchange. Django's dev server can't parse chunked bodies, causing `unsupported_grant_type` errors. nginx automatically de-chunks requests and sets `Content-Length` before forwarding to Django.

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

## Privacy & Support

- **Privacy Policy:** https://posthog.com/privacy
- **Terms of Service:** https://posthog.com/terms
- **Support:** https://posthog.com/questions or email support@posthog.com
- **GitHub Issues:** https://github.com/PostHog/posthog/issues

### Data handling

The MCP server acts as a proxy to your PostHog instance. It does not store your analytics data - all queries are executed against your PostHog project and results are returned directly to your AI client. Session state (active project/organization) is cached temporarily using Cloudflare Durable Objects tied to your API key hash.

For EU users, use the `mcp-eu.posthog.com` endpoint to ensure OAuth flows route to the EU PostHog instance.
