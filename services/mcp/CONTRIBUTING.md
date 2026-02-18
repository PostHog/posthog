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
│   │   └── ui-apps-constants.ts  # URI constants for each UI app
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

**Option 1: Using mprocs (Recommended)**

In mprocs, start both `mcp-ui-apps` and `mcp`:

1. Press `a` to see all processes
2. Navigate to `mcp-ui-apps` and press `s` to start (builds UI apps and watches for changes)
3. Navigate to `mcp` and press `s` to start (runs wrangler dev server)

The `mcp-ui-apps` process runs vite in watch mode. Changes to `src/ui-apps/` trigger rebuilds, and wrangler automatically reloads when `ui-apps-dist/` changes.

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

To add UI visualization to a tool using an existing UI app:

1. Import the resource URI constant:

   ```typescript
   import { QUERY_RESULTS_RESOURCE_URI } from '@/resources/ui-apps-constants'
   ```

2. Add `_meta.ui` to the tool definition:

   ```typescript
   const tool = (): ToolBase<typeof schema> => ({
     name: 'my-tool',
     schema,
     handler: myHandler,
     _meta: {
       ui: { resourceUri: QUERY_RESULTS_RESOURCE_URI },
     },
   })
   ```

3. Return data that the UI app expects (check the UI app's `main.tsx` for expected shape):

   ```typescript
   return {
       query: params.query,
       results: queryResult.data.results,
       _posthogUrl: buildUrl(context, params.query)
   }
   ```

### Adding a New UI App

When you need a completely new visualization (not just adding a tool to an existing UI app):

1. **Create the UI app folder** in `src/ui-apps/apps/`:

   ```bash
   mkdir -p src/ui-apps/apps/my-new-app
   ```

   Create `src/ui-apps/apps/my-new-app/index.html`:

   ```html
   <!DOCTYPE html>
   <html lang="en">
     <head>
       <meta charset="UTF-8" />
       <meta name="viewport" content="width=device-width, initial-scale=1.0" />
       <title>My New App</title>
     </head>
     <body>
       <div id="root"></div>
       <script type="module" src="./main.tsx"></script>
     </body>
   </html>
   ```

   Create `src/ui-apps/apps/my-new-app/main.tsx`:

   ```typescript
   import { createRoot } from 'react-dom/client'
   import { useToolResult } from '../../hooks/useToolResult'
   import '../../styles/base.css'

   function MyApp(): JSX.Element {
       const { data, isConnected, error } = useToolResult({
           appName: 'My New App',
       })

       if (error) return <div className="error">{error.message}</div>
       if (!isConnected) return <div className="loading">Connecting...</div>
       if (!data) return <div className="loading">Waiting for data</div>

       // Render your visualization based on data
       return <div>{JSON.stringify(data)}</div>
   }

   const container = document.getElementById('root')
   if (container) {
       createRoot(container).render(<MyApp />)
   }
   ```

   The app is auto-discovered by the build script - no vite config changes needed.

2. **Add URI constant** (`src/resources/ui-apps-constants.ts`):

   ```typescript
   /**
    * My new app visualization.
    * Used by: my-tool-name
    */
   export const MY_NEW_APP_RESOURCE_URI = 'ui://posthog/my-new-app.html'
   ```

3. **Register the resource** (`src/resources/ui-apps.ts`):

   ```typescript
   import myNewAppHtml from '../../ui-apps-dist/src/ui-apps/apps/my-new-app/index.html'
   import { MY_NEW_APP_RESOURCE_URI } from './ui-apps-constants'

   export async function registerUiAppResources(server: McpServer): Promise<void> {
     registerQueryResultsApp(server)
     registerMyNewApp(server) // Add this
   }

   function registerMyNewApp(server: McpServer): void {
     server.registerResource(
       'My New App',
       MY_NEW_APP_RESOURCE_URI,
       {
         mimeType: RESOURCE_MIME_TYPE,
         description: 'Description of what this visualizes',
       },
       async (uri) => ({
         contents: [
           {
             uri: uri.toString(),
             mimeType: RESOURCE_MIME_TYPE,
             text: myNewAppHtml,
           },
         ],
       })
     )
   }
   ```

4. **Reference from your tool**:

   ```typescript
   import { MY_NEW_APP_RESOURCE_URI } from '@/resources/ui-apps-constants'

   const tool = (): ToolBase<typeof schema> => ({
     name: 'my-tool',
     schema,
     handler: myHandler,
     _meta: {
       ui: { resourceUri: MY_NEW_APP_RESOURCE_URI },
     },
   })
   ```

5. **Build and test**:

   ```bash
   pnpm run build
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
