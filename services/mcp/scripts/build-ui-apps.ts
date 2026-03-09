#!/usr/bin/env tsx
/**
 * Build script for UI Apps.
 *
 * Auto-discovers UI apps from src/ui-apps/apps/ and builds each one
 * as a self-contained HTML file. Apps are built in parallel for speed,
 * each in its own Vite process with inlineDynamicImports to prevent
 * shared chunks.
 *
 * Usage:
 *   pnpm run build:ui-apps         # Build all apps
 *   pnpm run build:ui-apps:watch   # Watch mode for all apps
 */
import { exec, execSync } from 'child_process'
import { config as dotenvConfig } from 'dotenv'
import { existsSync, readdirSync, rmSync, statSync } from 'fs'
import { join, resolve } from 'path'

const ROOT_DIR = resolve(__dirname, '..')
const APPS_DIR = resolve(ROOT_DIR, 'src/ui-apps/apps')

// Load environment variables from .dev.vars (Cloudflare convention)
const devVarsPath = resolve(ROOT_DIR, '.dev.vars')
if (existsSync(devVarsPath)) {
    const output = dotenvConfig({ path: devVarsPath })
    const loadedKeys = Object.keys(output.parsed || {})
    console.info('📝 Loaded environment from .dev.vars', loadedKeys)
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

function buildAppAsync(appName: string): Promise<void> {
    if (!/^[a-z_-]+$/.test(appName)) {
        return Promise.reject(new Error(`Invalid app name "${appName}": must only contain a-z, underscore, or hyphen`))
    }

    return new Promise((resolve, reject) => {
        // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
        const child = exec('vite build --config vite.ui-apps.config.ts', {
            cwd: ROOT_DIR,
            env: {
                ...process.env,
                UI_APP: appName,
                BROWSERSLIST_IGNORE_OLD_DATA: '1',
                VITE_CJS_IGNORE_WARNING: '1',
            },
        })

        let stderr = ''
        child.stderr?.on('data', (data) => {
            stderr += data
        })

        child.on('close', (code) => {
            if (code !== 0) {
                console.error(`❌ ${appName} failed:\n${stderr}`)
                reject(new Error(`Build failed for ${appName} (exit code ${code})`))
            } else {
                console.info(`  ✓ ${appName}`)
                resolve()
            }
        })
    })
}

function buildAppSync(appName: string): void {
    if (!/^[a-z_-]+$/.test(appName)) {
        throw new Error(`Invalid app name "${appName}": must only contain a-z, underscore, or hyphen`)
    }

    // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
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

async function buildAllAppsParallel(apps: string[]): Promise<void> {
    console.info(`\n📦 Building ${apps.length} apps in parallel...`)
    await Promise.all(apps.map((app) => buildAppAsync(app)))
}

function watchApps(apps: string[]): void {
    console.info(`\n👀 Starting watch mode for ${apps.length} apps: ${apps.join(', ')}`)

    // Initial build sequentially (clearer output for debugging)
    for (const app of apps) {
        console.info(`\n📦 Building ${app}...`)
        buildAppSync(app)
    }
    console.info('\n✅ Initial build complete. Watching for changes...')

    import('chokidar').then(({ default: chokidar }) => {
        let isBuilding = false
        let pendingBuild = false

        const rebuild = async (): Promise<void> => {
            if (isBuilding) {
                pendingBuild = true
                return
            }

            isBuilding = true
            console.info('\n🔄 Rebuilding all apps...')

            try {
                await buildAllAppsParallel(apps)
                console.info('✅ Rebuild complete.')
            } catch (e) {
                console.error('❌ Build failed:', e)
            }

            isBuilding = false

            if (pendingBuild) {
                pendingBuild = false
                setTimeout(rebuild, 100)
            }
        }

        const watcher = chokidar.watch(
            [
                join(ROOT_DIR, 'src/ui-apps/**/*.{ts,tsx,css,html}'),
                resolve(ROOT_DIR, '../../common/mosaic/src/**/*.{ts,tsx,css}'),
            ],
            {
                ignoreInitial: true,
                awaitWriteFinish: {
                    stabilityThreshold: 100,
                    pollInterval: 50,
                },
            }
        )

        watcher.on('change', (path) => {
            console.info(`\n📝 File changed: ${path}`)
            rebuild()
        })

        watcher.on('add', (path) => {
            console.info(`\n➕ File added: ${path}`)
            rebuild()
        })

        const cleanup = (): void => {
            console.info('\n🛑 Stopping watcher...')
            watcher.close()
            process.exit(0)
        }

        process.on('SIGINT', cleanup)
        process.on('SIGTERM', cleanup)
    })
}

async function main(): Promise<void> {
    const isWatch = process.argv.includes('--watch')
    const apps = discoverApps()

    if (apps.length === 0) {
        console.error('❌ No UI apps found in src/ui-apps/apps/')
        process.exit(1)
    }

    console.info(`🔍 Discovered ${apps.length} UI app(s): ${apps.join(', ')}`)

    // Clean output directory before building
    const outDir = resolve(ROOT_DIR, 'ui-apps-dist')
    if (existsSync(outDir)) {
        rmSync(outDir, { recursive: true })
    }

    if (isWatch) {
        watchApps(apps)
    } else {
        await buildAllAppsParallel(apps)

        // Clean up shared assets directory after all builds complete.
        // Each app inlines its assets during build, so the assets/ folder
        // only contains intermediate files that are no longer needed.
        const assetsDir = resolve(outDir, 'assets')
        if (existsSync(assetsDir)) {
            rmSync(assetsDir, { recursive: true })
        }

        console.info('\n✅ All UI apps built successfully!')
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
