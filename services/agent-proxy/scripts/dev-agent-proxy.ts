import { spawn, type ChildProcess } from 'child_process'
import { context, type Plugin } from 'esbuild'
// esbuild watch + node respawn — same bundling pipeline as build-agent-proxy.ts so
// dev and prod behave identically.
import { existsSync } from 'fs'
import { resolve } from 'path'

import { agentProxyEsbuildOptions, agentProxyOutfile } from './agent-proxy-esbuild-config'

// Load the repo-root .env directly (the single source of truth that flox also
// loads). Reading it here means dev does not depend on flox's dotenv cache being
// fresh after you edit .env. A per-service services/agent-proxy/.env, if present,
// is loaded last as a local override.
for (const envPath of [resolve(process.cwd(), '../../.env'), resolve(process.cwd(), '.env')]) {
    if (existsSync(envPath)) {
        process.loadEnvFile(envPath)
    }
}

// flox sets SSL_CERT_FILE; Node's TLS layer only reads NODE_EXTRA_CA_CERTS.
if (!process.env.NODE_EXTRA_CA_CERTS && process.env.SSL_CERT_FILE) {
    process.env.NODE_EXTRA_CA_CERTS = process.env.SSL_CERT_FILE
}

let child: ChildProcess | undefined

const killChild = (): Promise<void> => {
    return new Promise((resolve) => {
        if (!child) {
            resolve()
            return
        }
        const proc = child
        child = undefined
        proc.removeAllListeners()
        proc.on('exit', () => resolve())
        proc.kill('SIGTERM')
    })
}

const launch = async (): Promise<void> => {
    await killChild()
    child = spawn(process.execPath, [agentProxyOutfile], {
        stdio: 'inherit',
        env: { ...process.env, SHUTDOWN_PRESTOP_DELAY_MS: '0' },
    })
    child.on('exit', (code, signal) => {
        if (signal === 'SIGTERM') {
            return
        }
        if (code !== 0) {
            console.warn(`[dev-agent-proxy] node exited with code=${code}; waiting for next rebuild...`)
        }
    })
}

const restartPlugin: Plugin = {
    name: 'dev-agent-proxy-restart',
    setup(build): void {
        build.onEnd((result) => {
            if (result.errors.length > 0) {
                console.error(`[dev-agent-proxy] build failed with ${result.errors.length} error(s); not restarting`)
                return
            }
            void launch()
        })
    },
}

async function main(): Promise<void> {
    const ctx = await context({
        ...agentProxyEsbuildOptions({ dev: true, extraPlugins: [restartPlugin] }),
        logLevel: 'info',
    })

    const shutdown = async (): Promise<void> => {
        if (child) {
            child.kill('SIGTERM')
        }
        await ctx.dispose()
        process.exit(0)
    }
    process.on('SIGINT', shutdown)
    process.on('SIGTERM', shutdown)

    await ctx.watch()
    console.info('[dev-agent-proxy] watching src/hono/** for changes')
}

main().catch((err: unknown) => {
    console.error('[dev-agent-proxy] fatal:', err)
    process.exit(1)
})
