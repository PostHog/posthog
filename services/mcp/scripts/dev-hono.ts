import { spawn, type ChildProcess } from 'child_process'
import { context, type Plugin } from 'esbuild'
// esbuild watch + node respawn — same bundling pipeline as build-hono.ts so
// dev and prod behave identically. tsx isn't used directly because it can't
// load the `.md` template imports or stub the `cloudflare:workers` builtin.
import { existsSync } from 'fs'
import { resolve } from 'path'

import { copyInstructions } from './copy-instructions'
import { honoEsbuildOptions, honoOutfile } from './hono-esbuild-config'

// Populate `shared/guidelines.md` so esbuild can inline it via `@shared/*`.
copyInstructions()

if (existsSync(resolve(process.cwd(), '.env'))) {
    process.loadEnvFile(resolve(process.cwd(), '.env'))
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
    child = spawn(process.execPath, [honoOutfile], {
        stdio: 'inherit',
        env: { ...process.env, SHUTDOWN_PRESTOP_DELAY_MS: '0' },
    })
    child.on('exit', (code, signal) => {
        if (signal === 'SIGTERM') {
            return
        }
        if (code !== 0) {
            console.warn(`[dev-hono] node exited with code=${code}; waiting for next rebuild...`)
        }
    })
}

const restartPlugin: Plugin = {
    name: 'dev-hono-restart',
    setup(build): void {
        build.onEnd((result) => {
            if (result.errors.length > 0) {
                console.error(`[dev-hono] build failed with ${result.errors.length} error(s); not restarting`)
                return
            }
            void launch()
        })
    },
}

async function main(): Promise<void> {
    const ctx = await context({
        ...honoEsbuildOptions({ dev: true, extraPlugins: [restartPlugin] }),
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
    console.info('[dev-hono] watching src/hono/** for changes')
}

main().catch((err: unknown) => {
    console.error('[dev-hono] fatal:', err)
    process.exit(1)
})
