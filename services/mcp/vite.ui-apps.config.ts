import react from '@vitejs/plugin-react'
import { existsSync, readdirSync } from 'fs'
import { resolve } from 'path'
import { defineConfig } from 'vite'

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

/**
 * Auto-discover UI apps from src/ui-apps/apps/ and generated/ subdirectory.
 * Returns app names like "debug", "query-results", "generated/action", etc.
 */
function discoverApps(): string[] {
    const apps = readdirSync(APPS_DIR)
        .filter((f) => f.endsWith('.tsx'))
        .map((f) => f.replace(/\.tsx$/, ''))

    const generatedDir = resolve(APPS_DIR, 'generated')
    if (existsSync(generatedDir)) {
        for (const f of readdirSync(generatedDir)) {
            if (f.endsWith('.tsx')) {
                apps.push(`generated/${f.replace(/\.tsx$/, '')}`)
            }
        }
    }

    return apps
}

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
        alias: {
            products: resolve(__dirname, '../../products'),
            '@posthog/mosaic': resolve(__dirname, '../../common/mosaic/src'),
            '@common': resolve(__dirname, '../../common'),
        },
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
