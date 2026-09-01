// End to end over a real mount directory and a real listening socket. Catches wiring
// regressions between the mount, the secrets it holds, auth and the routes that the
// per-module unit tests cannot see.

import { serve } from '@hono/node-server'
import { SignJWT } from 'jose'
import { mkdtemp, rename, rm, unlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { AUDIENCE } from '@/auth/types'
import type { Config } from '@/lib/config'
import { IntegrationServer } from '@/server'

const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const BURNED_KEY = 'STRIPE_APP_SECRET_KEY'
const SIGNING_KEY_ENTRY = '__CALLER_KEY_TEST_DEPLOYMENT'
const CALLER_SIGNING_KEY = 'e2e-caller-signing-key'
const OTHER_SIGNING_KEY = 'e2e-other-signing-key'

function config(mountDir: string): Config {
    return {
        port: 0,
        host: '127.0.0.1',
        shutdownPrestopDelayMs: 0,
        env: 'test',
        mountDir,
        reloadSeconds: 3600,
        metricsPort: 0,
    }
}

async function mint(opts: { signingKey: string; keys?: string[]; expiresIn?: string }): Promise<string> {
    return new SignJWT({ caller: 'warehouse-sources', keys: opts.keys ?? [KEY] })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(AUDIENCE)
        .setIssuedAt()
        .setExpirationTime(opts.expiresIn ?? '5m')
        .sign(new TextEncoder().encode(opts.signingKey))
}

function resolve(port: number, token: string): Promise<Response> {
    return fetch(`http://127.0.0.1:${port}/v1/secrets/resolve`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
    })
}

async function mountDir(values: Record<string, string>): Promise<string> {
    const dir = await mkdtemp(join(tmpdir(), 'integration-e2e-'))
    await Promise.all(Object.entries(values).map(([key, value]) => writeFile(join(dir, key), value)))
    return dir
}

interface Booted {
    server: IntegrationServer
    port: number
    exitCode: () => number | undefined
}

async function boot(dir: string): Promise<Booted> {
    let exitCode: number | undefined
    let announce!: (port: number) => void
    const listening = new Promise<number>((r) => {
        announce = r
    })
    const server = new IntegrationServer(config(dir), {
        serve: (options, listener) =>
            serve(options, (info) => {
                listener(info)
                announce(info.port)
            }),
        exit: (code) => {
            exitCode = code
        },
    })
    await server.start()
    return { server, port: await listening, exitCode: () => exitCode }
}

describe('integration server end to end', () => {
    it('serves, rotates, recovers and revokes against a live mount', async () => {
        const dir = await mountDir({
            // A trailing newline is what a human editing the secret by hand leaves behind.
            [KEY]: 'current-value-1\n',
            [BURNED_KEY]: 'sk-live-value',
            [SIGNING_KEY_ENTRY]: CALLER_SIGNING_KEY,
            __CALLER_KEY_OTHER_DEPLOYMENT: OTHER_SIGNING_KEY,
        })
        const { server, port, exitCode } = await boot(dir)
        const token = await mint({ signingKey: CALLER_SIGNING_KEY })

        try {
            const steady = await resolve(port, token)
            expect(steady.status).toBe(200)
            expect(await steady.json()).toMatchObject({
                secrets: { [KEY]: { state: 'steady', value: 'current-value-1' } },
                missing: [],
            })

            // A reserved entry is unservable even when a valid token names it, which is
            // what lets the signing keys share a mount with the secrets they protect.
            const reserved = await resolve(
                port,
                await mint({ signingKey: CALLER_SIGNING_KEY, keys: [SIGNING_KEY_ENTRY] })
            )
            const reservedBody = await reserved.text()
            expect(JSON.parse(reservedBody)).toEqual({ secrets: {}, missing: [SIGNING_KEY_ENTRY] })
            expect(reservedBody).not.toContain(CALLER_SIGNING_KEY)

            const expired = await resolve(port, await mint({ signingKey: CALLER_SIGNING_KEY, expiresIn: '-1s' }))
            expect(expired.status).toBe(401)

            const garbage = await resolve(port, 'not-a-jwt')
            expect(garbage.status).toBe(401)

            // A name nothing on the mount carries comes back in `missing`, per key, while
            // the rest of the request still succeeds.
            const unknown = await resolve(
                port,
                await mint({ signingKey: CALLER_SIGNING_KEY, keys: [KEY, 'NO_SUCH_INTEGRATION_KEY'] })
            )
            expect(await unknown.json()).toMatchObject({
                secrets: { [KEY]: { value: 'current-value-1' } },
                missing: ['NO_SUCH_INTEGRATION_KEY'],
            })

            // Start a rotation on the mount; the running server picks it up on reload.
            await writeFile(join(dir, `${KEY}_FALLBACKS`), 'staged-value-2')
            await server.reload()
            expect(await (await resolve(port, token)).json()).toMatchObject({
                secrets: { [KEY]: { state: 'rotating', value: 'current-value-1', previous: 'staged-value-2' } },
            })

            // Completing a rotation is deleting the sibling, and that has to end the
            // overlap rather than serving the retired value forever.
            await unlink(join(dir, `${KEY}_FALLBACKS`))
            await server.reload()
            const settled = (await (await resolve(port, token)).json()) as { secrets: Record<string, unknown> }
            expect(settled.secrets[KEY]).toMatchObject({ state: 'steady', value: 'current-value-1' })
            expect(settled.secrets[KEY]).not.toHaveProperty('previous')

            await writeFile(join(dir, 'INTEGRATION_RECOVERY_KEYS'), BURNED_KEY)
            await server.reload()
            const recovery = await resolve(port, await mint({ signingKey: CALLER_SIGNING_KEY, keys: [BURNED_KEY] }))
            const recoveryBody = await recovery.text()
            expect(JSON.parse(recoveryBody).secrets[BURNED_KEY]).toEqual(expect.objectContaining({ state: 'recovery' }))
            expect(JSON.parse(recoveryBody).secrets[BURNED_KEY]).not.toHaveProperty('value')
            expect(recoveryBody).not.toContain('sk-live-value')

            // The mount vanishing must not take a warm pod out: it keeps serving what it
            // holds, and readiness stays up.
            const held = join(tmpdir(), `integration-e2e-moved-${port}`)
            await rename(dir, held)
            await server.reload()
            expect((await resolve(port, token)).status).toBe(200)
            await rename(held, dir)
            await server.reload()

            // Revoke the caller: the same token must stop working, other callers must not.
            await unlink(join(dir, SIGNING_KEY_ENTRY))
            await server.reload()
            expect((await resolve(port, token)).status).toBe(401)
            expect((await resolve(port, await mint({ signingKey: OTHER_SIGNING_KEY }))).status).toBe(200)

            // The scrape lives on its own listener and never carries a secret value.
            const metricsPort = server.metricsPort()
            expect(metricsPort).toBeDefined()
            expect(metricsPort).not.toBe(port)
            const scrape = await fetch(`http://127.0.0.1:${metricsPort}/metrics`)
            expect(scrape.status).toBe(200)
            const scrapeBody = await scrape.text()
            expect(scrapeBody).toContain('integration_service_http_requests_total')
            expect(scrapeBody).not.toContain('current-value-1')
        } finally {
            await server.stop('SIGTERM')
            await rm(dir, { recursive: true, force: true })
        }
        expect(exitCode()).toBe(0)
    })

    // Boot has to fail closed. A pod that started with no signing keys would reject every
    // caller while reporting itself healthy, which reads as a caller-side outage.
    it('refuses to boot against a mount carrying no caller keys', async () => {
        const dir = await mkdtemp(join(tmpdir(), 'integration-e2e-empty-'))
        try {
            await expect(boot(dir)).rejects.toThrow(/no __CALLER_KEY_\* entries/)
        } finally {
            await rm(dir, { recursive: true, force: true })
        }
    })
})
