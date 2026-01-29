#!/usr/bin/env tsx
/**
 * Build script for UI Apps.
 *
 * Auto-discovers UI apps from src/ui-apps/apps/ and builds each one as a self-contained HTML file.
 *
 * Usage:
 *   pnpm run build:ui-apps         # Build all apps
 *   pnpm run build:ui-apps:watch   # Watch mode for all apps
 */

import { execSync, spawn, type ChildProcess } from 'child_process'
import { readdirSync, statSync, existsSync } from 'fs'
import { resolve, join } from 'path'
import { config as dotenvConfig } from 'dotenv'

const ROOT_DIR = resolve(__dirname, '..')
const APPS_DIR = resolve(ROOT_DIR, 'src/ui-apps/apps')

// Load environment variables from .dev.vars (Cloudflare convention)
const devVarsPath = resolve(ROOT_DIR, '.dev.vars')
if (existsSync(devVarsPath)) {
    const output = dotenvConfig({ path: devVarsPath })
    const loadedKeys = Object.keys(output.parsed || {})
    console.log('📝 Loaded environment from .dev.vars', loadedKeys)
}

function discoverApps(): string[] {
    const entries = readdirSync(APPS_DIR)
    const apps: string[] = []

    for (const entry of entries) {
        const entryPath = join(APPS_DIR, entry)
        const indexPath = join(entryPath, 'index.html')

        if (statSync(entryPath).isDirectory() && existsSync(indexPath)) {
            apps.push(entry)
        }
    }

    return apps
}

function buildApp(appName: string): void {
    console.log(`\n📦 Building ${appName}...`)
    execSync(`UI_APP=${appName} vite build --config vite.ui-apps.config.ts`, {
        cwd: ROOT_DIR,
        stdio: 'inherit',
        env: {
            ...process.env,
            UI_APP: appName,
            BROWSERSLIST_IGNORE_OLD_DATA: '1',
            VITE_CJS_IGNORE_WARNING: '1',
        },
    })
}

function buildAllApps(apps: string[]): void {
    for (const app of apps) {
        buildApp(app)
    }
}

function watchApps(apps: string[]): void {
    console.log(`\n👀 Starting watch mode for ${apps.length} apps: ${apps.join(', ')}`)

    // Do initial build of all apps sequentially
    buildAllApps(apps)
    console.log('\n✅ Initial build complete. Watching for changes...')

    // Use a single chokidar watcher for all source files
    import('chokidar').then(({ default: chokidar }) => {
        let isBuilding = false
        let pendingBuild = false

        const rebuildAll = () => {
            if (isBuilding) {
                pendingBuild = true
                return
            }

            isBuilding = true
            console.log('\n🔄 Rebuilding all apps...')

            try {
                buildAllApps(apps)
                console.log('✅ Rebuild complete.')
            } catch (e) {
                console.error('❌ Build failed:', e)
            }

            isBuilding = false

            if (pendingBuild) {
                pendingBuild = false
                // Debounce to avoid rapid rebuilds
                setTimeout(rebuildAll, 100)
            }
        }

        const watcher = chokidar.watch(join(ROOT_DIR, 'src/ui-apps/**/*.{ts,tsx,css,html}'), {
            ignoreInitial: true,
            awaitWriteFinish: {
                stabilityThreshold: 100,
                pollInterval: 50,
            },
        })

        watcher.on('change', (path) => {
            console.log(`\n📝 File changed: ${path}`)
            rebuildAll()
        })

        watcher.on('add', (path) => {
            console.log(`\n➕ File added: ${path}`)
            rebuildAll()
        })

        // Handle cleanup on exit
        const cleanup = () => {
            console.log('\n🛑 Stopping watcher...')
            watcher.close()
            process.exit(0)
        }

        process.on('SIGINT', cleanup)
        process.on('SIGTERM', cleanup)
    })
}

function main(): void {
    const isWatch = process.argv.includes('--watch')
    const apps = discoverApps()

    if (apps.length === 0) {
        console.error('❌ No UI apps found in src/ui-apps/apps/')
        process.exit(1)
    }

    console.log(`🔍 Discovered ${apps.length} UI app(s): ${apps.join(', ')}`)

    if (isWatch) {
        watchApps(apps)
    } else {
        // Build sequentially for production (overwrites existing files)
        for (const app of apps) {
            buildApp(app)
        }
        console.log('\n✅ All UI apps built successfully!')
    }
}

main()
