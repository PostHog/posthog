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
import { CredentialsServer } from '@/server'

const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const BURNED_KEY = 'STRIPE_APP_SECRET_KEY'
const RECOVERED_KEY = 'SLACK_APP_CLIENT_SECRET'
const REMOVED_KEY = 'GITHUB_APP_CLIENT_SECRET'
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
    const dir = await mkdtemp(join(tmpdir(), 'credentials-e2e-'))
    await Promise.all(Object.entries(values).map(([key, value]) => writeFile(join(dir, key), value)))
    return dir
}

interface Booted {
    server: CredentialsServer
    port: number
    exitCode: () => number | undefined
}

async function boot(dir: string): Promise<Booted> {
    let exitCode: number | undefined
    let announce!: (port: number) => void
    const listening = new Promise<number>((r) => {
        announce = r
    })
    const server = new CredentialsServer(config(dir), {
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

describe('credentials server end to end', () => {
    it('serves, rotates, recovers and revokes against a live mount', async () => {
        const dir = await mountDir({
            // A trailing newline is what a human editing the secret by hand leaves behind.
            [KEY]: 'current-value-1\n',
            [BURNED_KEY]: 'sk-live-value',
            [RECOVERED_KEY]: 'slack-value',
            [REMOVED_KEY]: 'github-value',
            [SIGNING_KEY_ENTRY]: CALLER_SIGNING_KEY,
            __CALLER_KEY_OTHER_DEPLOYMENT: OTHER_SIGNING_KEY,
            __ALLOWED_SECRETS_OTHER_DEPLOYMENT: KEY,
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
                await mint({ signingKey: CALLER_SIGNING_KEY, keys: [KEY, 'NO_SUCH_CREDENTIALS_KEY'] })
            )
            expect(await unknown.json()).toMatchObject({
                secrets: { [KEY]: { value: 'current-value-1' } },
                missing: ['NO_SUCH_CREDENTIALS_KEY'],
            })

            // Start a rotation on the mount; the running server picks it up on reload.
            await writeFile(join(dir, `${KEY}_FALLBACKS`), 'staged-value-2')
            await server.reload()
            const rotating = (await (await resolve(port, token)).json()) as { secrets: Record<string, unknown> }
            expect(rotating.secrets[KEY]).toMatchObject({
                state: 'rotating',
                value: 'current-value-1',
                incoming: 'staged-value-2',
            })
            expect(rotating.secrets[KEY]).not.toHaveProperty('previous')

            // Completing a rotation is deleting the sibling, and that has to end the
            // overlap rather than serving the retired value forever.
            await unlink(join(dir, `${KEY}_FALLBACKS`))
            await server.reload()
            const settled = (await (await resolve(port, token)).json()) as { secrets: Record<string, unknown> }
            expect(settled.secrets[KEY]).toMatchObject({ state: 'steady', value: 'current-value-1' })
            expect(settled.secrets[KEY]).not.toHaveProperty('incoming')
            expect(settled.secrets[KEY]).not.toHaveProperty('previous')

            await writeFile(join(dir, 'CREDENTIALS_RECOVERY_KEYS'), BURNED_KEY)
            await server.reload()
            const recovery = await resolve(port, await mint({ signingKey: CALLER_SIGNING_KEY, keys: [BURNED_KEY] }))
            const recoveryBody = await recovery.text()
            expect(JSON.parse(recoveryBody).secrets[BURNED_KEY]).toEqual(expect.objectContaining({ state: 'recovery' }))
            expect(JSON.parse(recoveryBody).secrets[BURNED_KEY]).not.toHaveProperty('value')
            expect(recoveryBody).not.toContain('sk-live-value')

            // The mount vanishing must not take a warm pod out: it keeps serving what it
            // holds, and readiness stays up.
            const held = join(tmpdir(), `credentials-e2e-moved-${port}`)
            await rename(dir, held)
            await server.reload()
            expect((await resolve(port, token)).status).toBe(200)
            await rename(held, dir)
            await server.reload()

            // An edit the key load refuses must not bring new values, or the keys still held would
            // read the values it rotated. What it takes away still lands.
            await writeFile(join(dir, '__ALLOWED_SECRETS_NO_SUCH_DEPLOYMENT'), KEY)
            await writeFile(join(dir, KEY), 'refused-value')
            await writeFile(join(dir, 'CREDENTIALS_RECOVERY_KEYS'), `${BURNED_KEY},${RECOVERED_KEY}`)
            await unlink(join(dir, REMOVED_KEY))
            await server.reload()
            const refused = await resolve(
                port,
                await mint({ signingKey: CALLER_SIGNING_KEY, keys: [KEY, RECOVERED_KEY, REMOVED_KEY] })
            )
            const refusedBody = (await refused.json()) as { secrets: Record<string, unknown> }
            expect(refusedBody).toMatchObject({
                secrets: { [KEY]: { value: 'current-value-1' }, [RECOVERED_KEY]: { state: 'recovery' } },
                missing: [REMOVED_KEY],
            })
            expect(refusedBody.secrets[RECOVERED_KEY]).not.toHaveProperty('value')
            await unlink(join(dir, '__ALLOWED_SECRETS_NO_SUCH_DEPLOYMENT'))
            await writeFile(join(dir, KEY), 'current-value-1')
            await server.reload()

            // Revoke the caller: the same token must stop working, other callers must not.
            await unlink(join(dir, SIGNING_KEY_ENTRY))
            await server.reload()
            expect((await resolve(port, token)).status).toBe(401)
            expect((await resolve(port, await mint({ signingKey: OTHER_SIGNING_KEY }))).status).toBe(200)

            // Revoking the last caller in the same edit as a rotation must refuse that caller,
            // or its old key would read the new value. Its allowlist stays behind, which makes
            // the key load refuse the snapshot.
            const lastCaller = await mint({ signingKey: OTHER_SIGNING_KEY })
            await unlink(join(dir, '__CALLER_KEY_OTHER_DEPLOYMENT'))
            await writeFile(join(dir, KEY), 'rotated-value-2')
            await server.reload()
            expect((await resolve(port, lastCaller)).status).toBe(401)

            // The scrape lives on its own listener and never carries a secret value.
            const metricsPort = server.metricsPort()
            expect(metricsPort).toBeDefined()
            expect(metricsPort).not.toBe(port)
            const scrape = await fetch(`http://127.0.0.1:${metricsPort}/metrics`)
            expect(scrape.status).toBe(200)
            const scrapeBody = await scrape.text()
            expect(scrapeBody).toContain('credentials_service_http_requests_total')
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
        const dir = await mkdtemp(join(tmpdir(), 'credentials-e2e-empty-'))
        try {
            await expect(boot(dir)).rejects.toThrow(/no __CALLER_KEY_\* entries/)
        } finally {
            await rm(dir, { recursive: true, force: true })
        }
    })
})
