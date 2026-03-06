import react from '@vitejs/plugin-react'
import { existsSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'fs'
import { resolve } from 'path'
import { type Plugin, defineConfig } from 'vite'

// PostHog configuration - injected at build time
// Set POSTHOG_UI_APPS_TOKEN to enable analytics in UI apps
const POSTHOG_UI_APPS_TOKEN = process.env.POSTHOG_UI_APPS_TOKEN || ''

// Analytics base URL for MCP Apps - where events are sent
// For local development, set to http://localhost:8010
const POSTHOG_MCP_APPS_ANALYTICS_BASE_URL =
    process.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL || 'https://us.i.posthog.com'

// Apps directory - all subdirectories with index.html are apps
const APPS_DIR = resolve(__dirname, 'src/ui-apps/apps')

// Single app mode: UI_APP env var selects which app to build
const appName = process.env.UI_APP

/**
 * Auto-discover UI apps from src/ui-apps/apps/
 */
function discoverApps(): string[] {
    const entries = readdirSync(APPS_DIR)
    const apps: string[] = []

    for (const entry of entries) {
        const entryPath = resolve(APPS_DIR, entry)
        const indexPath = resolve(entryPath, 'index.html')

        if (statSync(entryPath).isDirectory() && existsSync(indexPath)) {
            apps.push(entry)
        }
    }

    return apps
}

// Discover all apps for the inlining plugin
const ALL_APPS = discoverApps()

/**
 * Custom plugin that inlines JS and CSS into HTML files after the build.
 * Each app becomes a single self-contained HTML file with no external references.
 */
function inlineAllAssets(): Plugin {
    const outDir = resolve(__dirname, 'ui-apps-dist')

    // Only process the app being built (single-app mode)
    const appsToProcess = appName ? [appName] : ALL_APPS

    function readAsset(assetPath: string): string | null {
        const fullPath = resolve(outDir, assetPath.replace(/^\//, ''))
        try {
            return readFileSync(fullPath, 'utf-8')
        } catch {
            return null
        }
    }

    return {
        name: 'inline-all-assets',
        enforce: 'post',
        apply: 'build',
        closeBundle() {
            for (const app of appsToProcess) {
                const htmlPath = resolve(outDir, `src/ui-apps/apps/${app}/index.html`)

                try {
                    let html = readFileSync(htmlPath, 'utf-8')

                    // Remove modulepreload links (dependencies are bundled with inlineDynamicImports)
                    html = html.replace(/<link rel="modulepreload" crossorigin href="[^"]+">/g, '')

                    // Inline main JS module
                    html = html.replace(/<script type="module" crossorigin src="([^"]+)"><\/script>/g, (match, src) => {
                        const js = readAsset(src)
                        if (js) {
                            return `<script type="module">${js}</script>`
                        }
                        return match
                    })

                    // Inline CSS
                    html = html.replace(/<link rel="stylesheet" crossorigin href="([^"]+)">/g, (match, href) => {
                        const css = readAsset(href)
                        if (css) {
                            return `<style>${css}</style>`
                        }
                        return match
                    })

                    writeFileSync(htmlPath, html)
                    console.info(`[inline-all-assets] Inlined assets for ${app}`)
                } catch (e) {
                    if (app === appName) {
                        console.warn(`[inline-all-assets] Could not process ${app}:`, e)
                    }
                }
            }

            // Assets cleanup is handled by the build script after all apps are built,
            // to avoid race conditions when building in parallel.
            if (!appName) {
                // Only clean up in multi-app mode (single vite process builds all)
                const assetsDir = resolve(outDir, 'assets')
                if (existsSync(assetsDir)) {
                    rmSync(assetsDir, { recursive: true })
                    console.info(`[inline-all-assets] Cleaned up assets folder`)
                }
            }
        },
    }
}

/**
 * Vite config for building UI apps.
 *
 * Each app is built separately (via UI_APP env var) with inlineDynamicImports
 * to ensure fully self-contained HTML output with no shared chunks.
 * The build script runs apps in parallel to minimize total build time.
 *
 * Environment variables:
 * - POSTHOG_UI_APPS_TOKEN: PostHog API token for analytics (optional)
 * - POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: PostHog base URL for analytics
 */
export default defineConfig({
    plugins: [react(), inlineAllAssets()],
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
        outDir: 'ui-apps-dist',
        emptyOutDir: false, // Handled by build script
        cssCodeSplit: false,
        chunkSizeWarningLimit: 1000, // Suppress chunk size warnings (our bundles include React)
        rollupOptions: {
            input: appName
                ? resolve(APPS_DIR, `${appName}/index.html`)
                : Object.fromEntries(ALL_APPS.map((name) => [name, resolve(APPS_DIR, `${name}/index.html`)])),
            output: appName
                ? {
                      // Single app mode: inline everything into one bundle — no shared chunks
                      inlineDynamicImports: true,
                  }
                : {},
        },
    },
    logLevel: 'warn', // Reduce Vite output noise
})
