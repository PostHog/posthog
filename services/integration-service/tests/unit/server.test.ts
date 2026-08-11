import { SignJWT } from 'jose'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AUDIENCE } from '@/auth/types'
import type { Config } from '@/lib/config'
import { everyJittered, IntegrationServer } from '@/server'

const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const SIGNING_KEY = 'server-test-signing-key'

const dirs: string[] = []

afterEach(async () => {
    await Promise.all(dirs.splice(0).map((d) => rm(d, { recursive: true, force: true })))
})

async function secretsDir(): Promise<string> {
    const dir = await mkdtemp(join(tmpdir(), 'integration-server-'))
    dirs.push(dir)
    await writeFile(join(dir, KEY), 'hunter2-zx9q')
    await writeFile(join(dir, '__CALLER_KEY_TEST_DEPLOYMENT'), SIGNING_KEY)
    return dir
}

function config(mountDir: string, prestopDelayMs: number): Config {
    return {
        port: 0,
        host: '127.0.0.1',
        shutdownPrestopDelayMs: prestopDelayMs,
        env: 'test',
        mountDir,
        reloadSeconds: 3600,
        metricsToken: '',
    }
}

async function mint(): Promise<string> {
    return new SignJWT({ caller: 'warehouse-sources', keys: [KEY] })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(AUDIENCE)
        .setIssuedAt()
        .setExpirationTime('5m')
        .sign(new TextEncoder().encode(SIGNING_KEY))
}

interface Started {
    server: IntegrationServer
    events: string[]
    fetch: (req: Request) => Response | Promise<Response>
    exitCode: () => number | undefined
}

/** Start a real IntegrationServer with a fake listener and a captured exit. */
async function startServer(prestopDelayMs = 0): Promise<Started> {
    const events: string[] = []
    let exitCode: number | undefined
    let fetch!: Started['fetch']

    const server = new IntegrationServer(config(await secretsDir(), prestopDelayMs), {
        serve: (options) => {
            fetch = options.fetch as Started['fetch']
            return {
                close: (cb) => {
                    events.push(`drain draining=${server.lifecycleState().shuttingDown}`)
                    cb()
                },
            }
        },
        exit: (code) => {
            exitCode = code
        },
    })
    await server.start()
    return { server, events, fetch, exitCode: () => exitCode }
}

describe('integration server', () => {
    it('marks itself draining and waits out the prestop delay before draining the server', async () => {
        const { server, events, fetch } = await startServer(30)

        const res = await fetch(
            new Request('http://svc/v1/secrets/resolve', {
                method: 'POST',
                headers: { Authorization: `Bearer ${await mint()}` },
            })
        )
        expect(res.status).toBe(200)

        const stoppedAt = Date.now()
        await server.stop('SIGTERM')

        expect(events).toEqual(['drain draining=true'])
        // Kubernetes has to see the pod leave its endpoints before the listener closes.
        expect(Date.now() - stoppedAt).toBeGreaterThanOrEqual(25)
    })

    it('exits non-zero through the same graceful path on a crash', async () => {
        const { server, events, exitCode } = await startServer()

        await server.stop('uncaughtException', new Error('boom'))

        expect(events).toEqual(['drain draining=true'])
        expect(exitCode()).toBe(1)
    })

    it('stops only once and removes its process listeners', async () => {
        const before = process.listenerCount('SIGTERM')
        const { server, events, exitCode } = await startServer()
        expect(process.listenerCount('SIGTERM')).toBe(before + 1)

        await server.stop('SIGTERM')
        await server.stop('SIGTERM')

        expect(process.listenerCount('SIGTERM')).toBe(before)
        expect(events).toHaveLength(1)
        expect(exitCode()).toBe(0)
    })
})

// The reload is how a signing-key revocation reaches a running pod, so the cadence must
// never stretch past the configured interval, and replicas must not all reload at once.
describe('everyJittered', () => {
    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
    })

    it('runs first inside the interval, then on exactly that period', async () => {
        vi.useFakeTimers()
        // Worst-case initial draw: the first run must still land at the interval, not past it.
        vi.spyOn(Math, 'random').mockReturnValue(1)
        const runs: number[] = []
        const start = Date.now()

        const cancel = everyJittered(10_000, () => {
            runs.push(Date.now() - start)
            return Promise.resolve()
        })
        await vi.advanceTimersByTimeAsync(30_000)
        cancel()

        expect(runs).toEqual([10_000, 20_000, 30_000])
    })

    it('draws a different initial delay per replica', async () => {
        vi.useFakeTimers()
        vi.spyOn(Math, 'random').mockReturnValueOnce(0.1).mockReturnValueOnce(0.9)
        const firstRunAt: number[] = []
        const start = Date.now()
        const task = (): Promise<void> => {
            firstRunAt.push(Date.now() - start)
            return Promise.resolve()
        }

        const cancelA = everyJittered(10_000, task)
        const cancelB = everyJittered(10_000, task)
        await vi.advanceTimersByTimeAsync(9_500)
        cancelA()
        cancelB()

        expect(firstRunAt).toEqual([1_000, 9_000])
    })

    it('stops running once cancelled', async () => {
        vi.useFakeTimers()
        vi.spyOn(Math, 'random').mockReturnValue(0)
        const task = vi.fn().mockResolvedValue(undefined)

        const cancel = everyJittered(10_000, task)
        await vi.advanceTimersByTimeAsync(10_000)
        expect(task).toHaveBeenCalledTimes(2)

        cancel()
        await vi.advanceTimersByTimeAsync(60_000)
        expect(task).toHaveBeenCalledTimes(2)
    })
})
