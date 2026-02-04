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

// Get app name from env (set by build script) or undefined for multi-app mode
const appName = process.env.UI_APP

// Discover all apps for the inlining plugin
const ALL_APPS = discoverApps()

/**
 * Custom plugin that inlines JS and CSS into HTML files after the build.
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
                    // In single-app mode, only warn if the target app fails
                    if (app === appName) {
                        console.warn(`[inline-all-assets] Could not process ${app}:`, e)
                    }
                }
            }

            // Clean up assets folder since everything is inlined
            const assetsDir = resolve(outDir, 'assets')
            if (existsSync(assetsDir)) {
                rmSync(assetsDir, { recursive: true })
                console.info(`[inline-all-assets] Cleaned up assets folder`)
            }
        },
    }
}

/**
 * Vite config for building UI apps.
 *
 * In single-app mode (UI_APP env var set), builds one app with inlineDynamicImports.
 * This ensures each app is completely self-contained with no shared chunks.
 *
 * Environment variables:
 * - POSTHOG_UI_APPS_TOKEN: PostHog API token for analytics (optional)
 * - POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: PostHog base URL for analytics
 */
export default defineConfig({
    plugins: [react(), inlineAllAssets()],
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
                      // Single app mode: inline everything into one bundle
                      inlineDynamicImports: true,
                  }
                : {},
        },
    },
    logLevel: 'warn', // Reduce Vite output noise
})
