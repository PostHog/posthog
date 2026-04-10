# Contributing to PostHog MCP Server

This guide covers local development setup for the PostHog MCP server, including the ext-apps UI integration.

## Prerequisites

- Flox environment (see repo root for setup)
- A PostHog account with a personal API key

## Project Structure

```bash
services/mcp/
├── src/
│   ├── integrations/mcp/     # MCP server implementation
│   ├── tools/                # Tool definitions and handlers
│   ├── resources/            # MCP resources (skills, UI apps)
│   │   ├── ui-apps.ts        # Registers UI apps with MCP server
│   │   └── ui-apps.generated.ts  # URI constants for each UI app
│   ├── ui-apps/
│   │   ├── apps/             # UI apps (auto-discovered, one folder per app)
│   │   │   ├── query-results/    # For query-run & insight-query tools
│   │   │   │   ├── index.html
│   │   │   │   └── main.tsx
│   │   │   └── demo/         # Demo app for testing
│   │   ├── components/       # Shared visualization components
│   │   ├── hooks/            # Shared React hooks (useToolResult)
│   │   └── styles/           # Base CSS with CSS variables
│   └── schema/               # Zod schemas for API types
├── public/ui-apps/           # Built UI apps for Workers Static Assets (generated, gitignored)
├── dist/                     # npm package output (generated)
├── vite.ui-apps.config.ts    # Vite config for UI apps
├── tsup.config.ts            # tsup config for npm package
└── wrangler.jsonc            # Cloudflare Worker config
```

## Local Development

### 1. Start via phrocs (Recommended)

The MCP server is already configured in our phrocs setup. From the repo root:

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
cd services/mcp

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
cd services/mcp
pnpm run inspector
```

This opens a web interface where you can call tools and see responses.

## Testing with Claude Desktop (macOS)

Claude Desktop supports MCP servers with ext-apps UI rendering. To test the visualizations:

### 1. Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "posthog-dev": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://localhost:8787/mcp",
        "--header",
        "Authorization: Bearer <your_local_personal_posthog_key>"
      ]
    }
  }
}
```

NOTE: Claude Desktop does not support OAuth at the moment, you'll need to use a personal key.

### 2. Restart Claude Desktop

Quit (Cmd+Q) and reopen Claude Desktop.

### 3. Test Visualizations

Ask Claude to run a query:

- "Run a trends query for pageviews in the last 7 days"
- "Show me the signup funnel"
- "Query the events table"

The UI should render inline showing charts or tables with a "View in PostHog" link.

## Development Workflow

### Hot Reload for UI Changes

**Option 1: Using phrocs (Recommended)**

In phrocs, start both `mcp-ui-apps` and `mcp`:

1. Press `a` to see all processes
2. Navigate to `mcp-ui-apps` and press `s` to start (builds UI apps and watches for changes)
3. Navigate to `mcp` and press `s` to start (runs wrangler dev server)

The `mcp-ui-apps` process runs vite in watch mode. Changes to `src/ui-apps/` trigger rebuilds, and wrangler automatically reloads when `public/ui-apps/` changes.

**Option 2: Manual terminals**

Run the UI build in watch mode in one terminal:

```bash
cd services/mcp
pnpm run build:ui-apps -- --watch
```

And the MCP server in another:

```bash
pnpm run dev
```

Changes to `src/ui-apps/` will trigger a rebuild. Ask Claude a new query to see updated UI.

### Running Tests

```bash
cd services/mcp

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

**Smart visualizers** - Transform structured API data into charts:

- **Component** - Main entry point, infers visualization type from data structure
- **TrendsVisualizer** - Renders TrendsQuery results as line/bar/number
- **FunnelVisualizer** - Renders FunnelsQuery results as horizontal bars
- **TableVisualizer** - Renders HogQLQuery results, auto-detects simple formats

**Dumb chart components** (src/ui-apps/components/charts/) - Receive pre-processed data:

- **LineChart** - SVG line chart
- **BarChart** - SVG vertical bar chart
- **HorizontalBarChart** - SVG horizontal bar chart (for funnels)
- **BigNumber** - Large number display
- **DataTable** - HTML table with pagination

**Other**:

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

### Adding UI to an Existing Tool

Use `withUiApp(appKey, config)` to wrap a tool definition with UI app metadata,
`WithPostHogUrl<T>` for result types, and `withPostHogUrl(context, data, path)` to add the URL at runtime:

```typescript
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

type Result = WithPostHogUrl<{ results: MyData[] }>

export default (): ToolBase<typeof schema, Result> =>
  withUiApp('my-app', {
    name: 'my-tool',
    schema,
    handler: async (context, params) => {
      const data = await fetchData(context, params)
      return withPostHogUrl(context, { results: data }, '/my-feature')
    },
  })
```

`withUiApp` accepts the full tool config and injects `_meta` — you never construct `_meta` manually.
The `appKey` parameter is type-checked against the generated `UiAppKey` union (invalid keys are compile-time errors).
Valid keys are defined in `products/*/mcp/tools.yaml` under `ui_apps`.

### Adding a New UI App (Generated)

Most UI apps (detail and list views) are auto-generated from YAML.
Add a `ui_apps` section to your product's `mcp/tools.yaml`.
Most fields are derived by convention — you only specify what differs.

**Detail app** — only `view_prop` is required (the prop name your view component accepts):

```yaml
ui_apps:
  my-entity:
    type: detail
    view_prop: data
```

**List app** — only `detail_tool` is required (the tool to call when clicking an item):

```yaml
ui_apps:
  my-entity-list:
    type: list
    detail_tool: my-entity-get
```

Convention defaults (derived from the app key and product directory):

- `app_name` → `"PostHog My Entity"` / `"PostHog My Entity List"`
- `component_import` → `products/{product}/mcp/apps`
- `data_type` → `MyEntityData`, `view_component` → `MyEntityView`
- `list_data_type` → `MyEntityListData`, `item_data_type` → `MyEntityData`
- `click_prop` → `onMyEntityClick`, `detail_args` → `{ id: item.id }`
- `item_name_field` → `name`, `entity_label` → `my entity`

Override any field explicitly when the convention doesn't match
(e.g. `click_prop: onFlagClick`, `detail_args: "{ flagId: item.id }"`).

**Link tools to apps** with `ui_app`:

```yaml
tools:
  my-entity-get:
    ui_app: my-entity # references the key in ui_apps above
```

Then regenerate and build:

```bash
pnpm run generate:ui-apps   # generates entry points + registry
pnpm run build               # builds all apps
```

### Adding a New UI App (Custom / Manual)

For apps that need fully custom logic (like `debug.tsx` or `query-results.tsx`):

1. **Add a `type: custom` entry** in the YAML to register the URI and app name:

   ```yaml
   ui_apps:
     my-custom-app:
       type: custom
       app_name: My Custom App
       description: Custom visualization for X
   ```

2. **Create the entry point** manually at `src/ui-apps/apps/my-custom-app.tsx`.
   This file will NOT be overwritten by the generator.

3. **Regenerate** to pick up the registry entry:

   ```bash
   pnpm run generate:ui-apps
   ```

4. **Reference from your tool**:

   ```typescript
   export default () => withUiApp('my-custom-app', { name: 'my-tool', schema, handler })
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

- Tools import `withUiApp` from `@/resources/ui-apps.generated` (not `ui-apps.ts`)
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
