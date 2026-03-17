#!/usr/bin/env tsx
/**
 * Build script for UI Apps.
 *
 * Auto-discovers UI apps from src/ui-apps/apps/ and builds each one
 * as separate JS + CSS files served via Workers Static Assets.
 * Apps are built in parallel for speed, each in its own Vite process
 * with inlineDynamicImports to prevent shared chunks.
 *
 * Usage:
 *   pnpm run build:ui-apps         # Build all apps
 *   pnpm run build:ui-apps:watch   # Watch mode for all apps
 */
import { exec } from 'child_process'
import { config as dotenvConfig } from 'dotenv'
import { existsSync, readdirSync, rmSync } from 'fs'
import { join, resolve } from 'path'

const MCP_ROOT_DIR = resolve(__dirname, '..')
const ROOT_DIR = resolve(MCP_ROOT_DIR, '..', '..')
const APPS_DIR = resolve(MCP_ROOT_DIR, 'src/ui-apps/apps')
const OUT_DIR = resolve(MCP_ROOT_DIR, 'public/ui-apps')

// Load environment variables from .dev.vars (Cloudflare convention)
const devVarsPath = resolve(MCP_ROOT_DIR, '.dev.vars')
if (existsSync(devVarsPath)) {
    const output = dotenvConfig({ path: devVarsPath })
    const loadedKeys = Object.keys(output.parsed || {})
    console.info('📝 Loaded environment from .dev.vars', loadedKeys)
}

function discoverApps(): string[] {
    // Top-level custom/manual apps
    const apps = readdirSync(APPS_DIR)
        .filter((f) => f.endsWith('.tsx'))
        .map((f) => f.replace(/\.tsx$/, ''))

    // Generated apps in the generated/ subdirectory
    const generatedDir = join(APPS_DIR, 'generated')
    if (existsSync(generatedDir)) {
        for (const f of readdirSync(generatedDir)) {
            if (f.endsWith('.tsx')) {
                apps.push(`generated/${f.replace(/\.tsx$/, '')}`)
            }
        }
    }

    return apps
}

function buildAppAsync(appName: string): Promise<void> {
    if (!/^(?:generated\/)?[a-z_-]+$/.test(appName)) {
        return Promise.reject(
            new Error(`Invalid app name "${appName}": must only contain a-z, underscore, hyphen, or generated/ prefix`)
        )
    }

    return new Promise((resolve, reject) => {
        // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
        const child = exec('vite build --config vite.ui-apps.config.ts', {
            cwd: MCP_ROOT_DIR,
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

async function buildAllAppsParallel(apps: string[]): Promise<void> {
    // CI environments have limited memory — limit concurrency to avoid OOM kills
    const concurrency = process.env.CI ? 4 : apps.length

    if (concurrency < apps.length) {
        console.info(`\n📦 Building ${apps.length} apps (concurrency: ${concurrency})...`)
        const remaining = [...apps]
        const workers: Promise<void>[] = []

        async function next(): Promise<void> {
            while (remaining.length > 0) {
                const app = remaining.shift()!
                await buildAppAsync(app)
            }
        }

        for (let i = 0; i < concurrency; i++) {
            workers.push(next())
        }

        await Promise.all(workers)
    } else {
        console.info(`\n📦 Building ${apps.length} apps in parallel...`)
        await Promise.all(apps.map((app) => buildAppAsync(app)))
    }
}

async function watchApps(apps: string[]): Promise<void> {
    console.info(`\n👀 Starting watch mode for ${apps.length} apps: ${apps.join(', ')}`)

    await buildAllAppsParallel(apps)
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
                join(MCP_ROOT_DIR, 'src/ui-apps/**/*.{ts,tsx,css}'),
                join(ROOT_DIR, 'products/**/mcp/apps/**/*.{ts,tsx,css}'),
                join(ROOT_DIR, 'common/mosaic/src/**/*.{ts,tsx,css}'),
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
    if (existsSync(OUT_DIR)) {
        rmSync(OUT_DIR, { recursive: true })
    }

    if (isWatch) {
        await watchApps(apps)
    } else {
        await buildAllAppsParallel(apps)

        console.info('\n✅ All UI apps built successfully!')
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
