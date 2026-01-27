# Contributing to PostHog MCP Server

This guide covers local development setup for the PostHog MCP server, including the ext-apps UI integration.

## Prerequisites

- Flox environment (see repo root for setup)
- A PostHog account with a personal API key

## Project Structure

```t
services/mcp/typescript/
├── src/
│   ├── integrations/mcp/     # MCP server implementation
│   ├── tools/                # Tool definitions and handlers
│   ├── resources/            # MCP resources (skills, UI apps)
│   ├── ui-apps/              # React UI app source
│   │   ├── components/       # Visualization library (extractable)
│   │   ├── styles/           # Base CSS with CSS variables
│   │   └── app/              # MCP ext-apps entry point
│   └── schema/               # Zod schemas for API types
├── ui-apps-dist/             # Built UI apps (generated, gitignored)
├── dist/                     # npm package output (generated)
├── vite.ui-apps.config.ts    # Vite config for UI apps
├── tsup.config.ts            # tsup config for npm package
└── wrangler.jsonc            # Cloudflare Worker config
```

## Local Development

### 1. Start via mprocs (Recommended)

The MCP server is already configured in our mprocs setup. From the repo root:

```bash
# Start the full stack (includes MCP server)
hogli start

# Or start with the minimal stack
hogli start --minimal
```

The MCP server will be available at `http://localhost:8787`.

### 2. Manual Start

If you need to run the MCP server standalone:

```bash
cd services/mcp/typescript

# Copy env file if needed
cp .dev.vars.example .dev.vars

# Install dependencies
pnpm install

# Build UI apps (required before running)
pnpm run build:ui-apps

# Start the server
pnpm run dev
```

### 3. Test with MCP Inspector

Use the MCP Inspector to test tools:

```bash
cd services/mcp/typescript
pnpm run inspector
```

This opens a web interface where you can call tools and see responses.

## Testing with Claude Desktop (macOS)

Claude Desktop supports MCP servers with ext-apps UI rendering. To test the visualizations:

### 1. Expose Local Server via Cloudflared

Cloudflared is included in the flox environment:

```bash
# In a separate terminal
cloudflared tunnel --url http://localhost:8787
```

Copy the generated `https://xxx.trycloudflare.com` URL.

### 2. Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "posthog-dev": {
      "url": "https://xxx.trycloudflare.com/mcp",
      "headers": {
        "Authorization": "Bearer phx_your_posthog_personal_api_key"
      }
    }
  }
}
```

### 3. Restart Claude Desktop

Quit (Cmd+Q) and reopen Claude Desktop.

### 4. Test Visualizations

Ask Claude to run a query:

- "Run a trends query for pageviews in the last 7 days"
- "Show me the signup funnel"
- "Query the events table"

The UI should render inline showing charts or tables with a "View in PostHog" link.

## Development Workflow

### Hot Reload for UI Changes

Run the UI build in watch mode in one terminal:

```bash
cd services/mcp/typescript
pnpm run build:ui-apps -- --watch
```

And the MCP server in another:

```bash
pnpm run dev
```

Changes to `src/ui-apps/` will trigger a rebuild. Ask Claude a new query to see updated UI.

### Running Tests

```bash
cd services/mcp/typescript

# Unit tests
pnpm run test

# Integration tests (requires TEST_* env vars)
pnpm run test:integration

# Watch mode
pnpm run test:watch
```

### Type Checking

```bash
pnpm run typecheck
```

### Building for Production

```bash
pnpm run build
```

This runs:

1. `build:ui-apps` - Builds React components to single HTML
2. `tsup` - Builds npm package (CJS + ESM)

## UI Apps Architecture

The visualization system is designed to be extractable to a standalone `@posthog/query-visualizer` package:

### Components (src/ui-apps/components/)

- **QueryVisualizer** - Main entry point, auto-selects visualization by query type
- **TrendsVisualizer** - SVG line/bar charts for TrendsQuery
- **FunnelVisualizer** - Horizontal funnel bars for FunnelsQuery
- **TableVisualizer** - Data table for HogQLQuery results
- **PostHogLink** - "View in PostHog" button

### Theming

Components use CSS variables from the ext-apps SDK that the host provides:

- `--color-text-primary`, `--color-text-secondary`
- `--color-background-primary`, `--color-background-secondary`
- `--color-border-primary`
- `--font-sans`, `--font-mono`
- `--border-radius-sm`, `--border-radius-md`, `--border-radius-lg`

Chart colors are PostHog-specific (`--posthog-chart-1` through `--posthog-chart-5`) since the ext-apps SDK doesn't provide chart colors.

Default values are provided for light/dark mode via `prefers-color-scheme`.

### Adding UI to a Tool

1. Import the resource URI:

   ```typescript
   import { QUERY_VISUALIZER_RESOURCE_URI } from '@/resources/ui-apps-constants'
   ```

2. Add `_meta.ui` to the tool definition:

   ```typescript
   const tool = (): ToolBase<typeof schema> => ({
     name: 'my-tool',
     schema,
     handler: myHandler,
     _meta: {
       ui: { resourceUri: QUERY_VISUALIZER_RESOURCE_URI },
     },
   })
   ```

3. Return data with `query`, `results`, and `_posthogUrl`:

   ```typescript
   return {
       query: params.query,
       results: queryResult.data.results,
       _posthogUrl: buildUrl(context, params.query)
   }
   ```

## Deployment

The MCP server is deployed to Cloudflare Workers. Deployment is handled by CI/CD:

- **CI** (`.github/workflows/ci-mcp.yml`): Runs tests on PRs and master
- **Publish** (`.github/workflows/mcp-publish.yml`): Publishes to npm on version bump

To deploy manually to Cloudflare:

```bash
pnpm run deploy
```

## Troubleshooting

### "No loader configured for .html files"

The HTML import only works with wrangler's Text rule. If you see this error during `tsup` build, ensure:

- Tools import from `@/resources/ui-apps-constants` (not `ui-apps.ts`)
- The HTML import is only in `src/resources/ui-apps.ts`

### UI not rendering in Claude Desktop

1. Verify the tunnel is running (`cloudflared tunnel --url ...`)
2. Check Claude Desktop config has correct URL
3. Restart Claude Desktop after config changes
4. Verify tool has `_meta.ui.resourceUri` set

### Tests failing

Ensure you've built the UI apps first:

```bash
pnpm run build:ui-apps
```
