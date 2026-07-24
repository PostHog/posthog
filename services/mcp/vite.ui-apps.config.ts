import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { defineConfig } from 'vite'

import { discoverApps } from './scripts/utils'

// PostHog configuration - injected at build time
// Set POSTHOG_UI_APPS_TOKEN to enable analytics in UI apps
const POSTHOG_UI_APPS_TOKEN = process.env.POSTHOG_UI_APPS_TOKEN || ''

// Analytics base URL for MCP Apps - where events are sent
// For local development, set to http://localhost:8010
const POSTHOG_MCP_APPS_ANALYTICS_BASE_URL =
    process.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL || 'https://us.i.posthog.com'

// Apps directory - each .tsx file is an app
const APPS_DIR = resolve(__dirname, 'src/ui-apps/apps')

// Single app mode: UI_APP env var selects which app to build
const appName = process.env.UI_APP

// Discover all apps
const ALL_APPS = discoverApps()

/**
 * Vite config for building UI apps.
 *
 * Each app is built separately (via UI_APP env var) with inlineDynamicImports
 * to produce a single JS bundle + CSS file. Output goes to public/ui-apps/{app}/
 * for Workers Static Assets to serve.
 *
 * Entry points are .tsx files directly — no HTML needed since the runtime
 * generates stub HTML that loads the built JS+CSS from static assets.
 *
 * Environment variables:
 * - POSTHOG_UI_APPS_TOKEN: PostHog API token for analytics (optional)
 * - POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: PostHog base URL for analytics
 */
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: [
            { find: 'products', replacement: resolve(__dirname, '../../products') },
            { find: '@posthog/mcp-ui', replacement: resolve(__dirname, 'src/ui-apps/lib') },
            // Resolve Quill explicitly so files imported via the `products` alias
            // (which live outside this package's node_modules tree) can find it.
            // Match exact import (`@posthog/quill`) -> dist/index.js, but leave
            // subpath imports (`@posthog/quill/tokens.css`, etc.) to fall through
            // to the package's exports map.
            {
                find: /^@posthog\/quill$/,
                replacement: resolve(__dirname, '../../packages/quill/packages/quill/dist/index.js'),
            },
            // quill-charts is consumed as source (its package main is src/index.ts); resolve it
            // explicitly so files reached via the `products` alias — and the local chart wrappers —
            // can find it without a node_modules symlink.
            {
                find: /^@posthog\/quill-charts$/,
                replacement: resolve(__dirname, '../../packages/quill/packages/charts/src/index.ts'),
            },
            // lucide-react, react, and react-dom aren't reachable from files
            // resolved via the `products` alias (products/ isn't a dep of this
            // package), so pin them to this package's copies. react needs its
            // subpaths covered too: Vite 7 resolves the injected react/jsx-runtime
            // import relative to the importing file.
            { find: /^lucide-react$/, replacement: resolve(__dirname, 'node_modules/lucide-react') },
            { find: 'react', replacement: resolve(__dirname, 'node_modules/react') },
            { find: 'react-dom', replacement: resolve(__dirname, 'node_modules/react-dom') },
            { find: '@common', replacement: resolve(__dirname, '../../common') },
        ],
    },
    define: {
        // Inject PostHog configuration at build time
        __POSTHOG_UI_APPS_TOKEN__: JSON.stringify(POSTHOG_UI_APPS_TOKEN),
        __POSTHOG_MCP_APPS_ANALYTICS_BASE_URL__: JSON.stringify(POSTHOG_MCP_APPS_ANALYTICS_BASE_URL),
    },
    build: {
        outDir: 'public/ui-apps',
        emptyOutDir: false, // Handled by build script
        cssCodeSplit: false,
        chunkSizeWarningLimit: 1000, // Suppress chunk size warnings (our bundles include React)
        rollupOptions: {
            input: appName
                ? resolve(APPS_DIR, `${appName}.tsx`)
                : Object.fromEntries(ALL_APPS.map((name) => [name, resolve(APPS_DIR, `${name}.tsx`)])),
            output: appName
                ? {
                      // Single app mode: inline everything into one bundle — no shared chunks
                      inlineDynamicImports: true,
                      // IIFE format avoids CORS issues when loading scripts cross-origin from sandboxed iframes
                      format: 'iife' as const,
                      // Predictable filenames so stub HTML can reference them without a manifest
                      entryFileNames: `${appName}/main.js`,
                      assetFileNames: `${appName}/styles[extname]`,
                  }
                : {}, // Multi-app fallback — uses hashed filenames, not compatible with buildAppStubHtml. Always use the build script (which sets UI_APP per app).
        },
    },
    logLevel: 'warn', // Reduce Vite output noise
})
