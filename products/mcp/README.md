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

- What feature flags do I have active?
- Add a new feature flag for our homepage redesign
- What are my most common errors?
- Show me my LLM costs this week

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
