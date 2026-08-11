// End-to-end over a real mount directory and a real listening socket: mint a JWT, resolve a
// credential, rotate it by writing the `_FALLBACKS` sibling, then revoke the caller by
// removing its signing key. Catches wiring regressions between the mount, the snapshot,
// auth and the routes that the per-module unit tests cannot see.

import { serve } from '@hono/node-server'
import { SignJWT } from 'jose'
import { mkdtemp, rm, unlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { AUDIENCE } from '@/auth/types'
import type { Config } from '@/lib/config'
import { IntegrationServer } from '@/server'

const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const CALLER_SIGNING_KEY = 'e2e-caller-signing-key'
const OTHER_SIGNING_KEY = 'e2e-other-signing-key'

function config(mountDir: string): Config {
    return {
        port: 0,
        host: '127.0.0.1',
        shutdownPrestopDelayMs: 0,
        env: 'test',
        mountDir,
        databaseUrl: undefined,
        reloadSeconds: 3600,
        usageFlushMs: 3_600_000,
        retentionDays: 9,
        metricsToken: '',
    }
}

async function mint(signingKey: string): Promise<string> {
    return new SignJWT({ caller: 'warehouse-sources', keys: [KEY] })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(AUDIENCE)
        .setIssuedAt()
        .setExpirationTime('5m')
        .sign(new TextEncoder().encode(signingKey))
}

function resolve(port: number, token: string): Promise<Response> {
    return fetch(`http://127.0.0.1:${port}/v1/secrets/resolve`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
    })
}

describe('integration server end to end', () => {
    it('serves a credential, rotates it on reload, and revokes a caller on reload', async () => {
        const dir = await mkdtemp(join(tmpdir(), 'integration-e2e-'))
        await writeFile(join(dir, KEY), 'current-value-1')
        await writeFile(join(dir, '__CALLER_KEY_TEST_DEPLOYMENT'), CALLER_SIGNING_KEY)
        await writeFile(join(dir, '__CALLER_KEY_OTHER_DEPLOYMENT'), OTHER_SIGNING_KEY)

        let exitCode: number | undefined
        let resolvePort!: (port: number) => void
        const listening = new Promise<number>((r) => {
            resolvePort = r
        })
        const server = new IntegrationServer(config(dir), {
            serve: (options, listener) =>
                serve(options, (info) => {
                    listener(info)
                    resolvePort(info.port)
                }),
            exit: (code) => {
                exitCode = code
            },
        })

        try {
            await server.start()
            const port = await listening
            const token = await mint(CALLER_SIGNING_KEY)

            const steady = await resolve(port, token)
            expect(steady.status).toBe(200)
            expect(await steady.json()).toMatchObject({
                secrets: { [KEY]: { state: 'steady', value: 'current-value-1' } },
                missing: [],
            })

            // Start a rotation on the mount; the running server picks it up on reload.
            await writeFile(join(dir, `${KEY}_FALLBACKS`), 'previous-value-0')
            await server.reload()
            const rotating = await resolve(port, token)
            expect(rotating.status).toBe(200)
            expect(await rotating.json()).toMatchObject({
                secrets: { [KEY]: { state: 'rotating', value: 'current-value-1', previous: 'previous-value-0' } },
            })

            // Revoke the caller: the same token must stop working, other callers must not.
            await unlink(join(dir, '__CALLER_KEY_TEST_DEPLOYMENT'))
            await server.reload()
            expect((await resolve(port, token)).status).toBe(401)
            expect((await resolve(port, await mint(OTHER_SIGNING_KEY))).status).toBe(200)
        } finally {
            await server.stop('SIGTERM')
            await rm(dir, { recursive: true, force: true })
        }
        expect(exitCode).toBe(0)
    })
})
