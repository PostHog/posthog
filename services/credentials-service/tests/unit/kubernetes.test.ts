import { SignJWT } from 'jose'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AUDIENCE } from '@/auth/types'
import { KubernetesSecretSource } from '@/kubernetes'
import type { Config } from '@/lib/config'
import { mountErrorsTotal, register, secretWatchRestartsTotal, servingStaleSeconds } from '@/metrics'
import { CredentialsServer } from '@/server'
import type { SecretSnapshot } from '@/source'

const NAMESPACE = 'posthog'
const SECRET_NAME = 'credentials-service-secrets'
const KEY = 'HUBSPOT_APP_CLIENT_SECRET'
const SIGNING_KEY = 'k8s-test-signing-key'
const NEW_SIGNING_KEY = 'k8s-test-signing-key-new'

const WAIT = { timeout: 2000, interval: 5 }

interface Recorded {
    query: URLSearchParams
    auth: string | undefined
}

interface Watch extends Recorded {
    res: ServerResponse
    closed: boolean
}

/** Answers the list and watch calls the source makes, the way the API server does. */
class FakeApiServer {
    secret: { resourceVersion: string; data: Record<string, string> } | null = null
    listResourceVersion = '100'
    listStatus = 200
    /** Statuses to answer the next watch connections with, instead of opening a stream. */
    watchStatuses: number[] = []
    /** While set, list responses wait for it, so a test can deliver a watch event first. */
    holdLists: Promise<void> | null = null
    /** Like `holdLists`, but only for the next list, which is answered with the secret as it is now. */
    holdNextList: Promise<void> | null = null
    readonly lists: Recorded[] = []
    readonly watches: Watch[] = []

    private readonly server: Server = createServer((req, res) => void this.handle(req, res))

    async start(): Promise<string> {
        await new Promise<void>((resolve) => this.server.listen(0, '127.0.0.1', resolve))
        return `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`
    }

    async close(): Promise<void> {
        this.server.closeAllConnections()
        await new Promise<void>((resolve) => this.server.close(() => resolve()))
    }

    get openWatch(): Watch | undefined {
        return this.watches.filter((watch) => !watch.closed).at(-1)
    }

    /** Write one event to the open watch. */
    send(type: string, object: object): void {
        const watch = this.openWatch
        if (!watch) {
            throw new Error('no open watch')
        }
        watch.res.write(`${JSON.stringify({ type, object })}\n`)
    }

    private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
        const url = new URL(req.url ?? '/', 'http://fake')
        expect(url.pathname).toBe(`/api/v1/namespaces/${NAMESPACE}/secrets`)
        const recorded = { query: url.searchParams, auth: req.headers.authorization }

        if (url.searchParams.get('watch') === '1') {
            const status = this.watchStatuses.shift()
            const watch: Watch = { ...recorded, res, closed: status !== undefined }
            this.watches.push(watch)
            if (status !== undefined) {
                res.statusCode = status
                res.end()
                return
            }
            res.on('close', () => {
                watch.closed = true
            })
            res.writeHead(200, { 'Content-Type': 'application/json' })
            res.flushHeaders()
            return
        }

        this.lists.push(recorded)
        const held = this.holdNextList
        this.holdNextList = null
        const body = JSON.stringify({
            kind: 'SecretList',
            metadata: { resourceVersion: this.listResourceVersion },
            items: this.secret ? [secretObject(this.secret.resourceVersion, this.secret.data)] : [],
        })
        await held
        await this.holdLists
        if (this.listStatus !== 200) {
            res.statusCode = this.listStatus
            res.end()
            return
        }
        res.end(body)
    }
}

function secretObject(resourceVersion: string, values: Record<string, string>): object {
    return {
        metadata: { name: SECRET_NAME, namespace: NAMESPACE, resourceVersion },
        data: Object.fromEntries(Object.entries(values).map(([k, v]) => [k, Buffer.from(v).toString('base64')])),
    }
}

const cleanups: (() => Promise<void> | void)[] = []

afterEach(async () => {
    for (const cleanup of cleanups.splice(0).reverse()) {
        await cleanup()
    }
    vi.useRealTimers()
})

async function fakeApi(values: Record<string, string> | null): Promise<{ api: FakeApiServer; url: string }> {
    const api = new FakeApiServer()
    if (values) {
        api.secret = { resourceVersion: '90', data: values }
    }
    const url = await api.start()
    cleanups.push(() => api.close())
    return { api, url }
}

async function tokenFile(token: string): Promise<string> {
    const dir = await mkdtemp(join(tmpdir(), 'credentials-k8s-'))
    cleanups.push(() => rm(dir, { recursive: true, force: true }))
    const file = join(dir, 'token')
    await writeFile(file, token)
    return file
}

async function kubernetesSource(apiUrl: string, tokenPath?: string): Promise<KubernetesSecretSource> {
    const source = new KubernetesSecretSource({
        apiUrl,
        namespace: NAMESPACE,
        secretName: SECRET_NAME,
        tokenFile: tokenPath ?? (await tokenFile('token-1')),
        caFile: '/nonexistent/ca.crt',
        backoff: { initialMs: 1, maxMs: 5 },
    })
    cleanups.push(() => source.stop())
    return source
}

async function restarts(reason: string): Promise<number> {
    const values = (await secretWatchRestartsTotal.get()).values
    return values.find((v) => v.labels.reason === reason)?.value ?? 0
}

describe('kubernetes secret source', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    it('lists the secret by field selector and decodes it into one snapshot', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'sec\n', __CALLER_KEY_POSTHOG_DJANGO: SIGNING_KEY })
        const source = await kubernetesSource(url)

        expect(await source.read()).toEqual({
            values: { [KEY]: 'sec', __CALLER_KEY_POSTHOG_DJANGO: SIGNING_KEY },
            revision: '90',
        })
        // RBAC restricted by resourceNames denies a list without this selector.
        expect(api.lists[0]?.query.get('fieldSelector')).toBe(`metadata.name=${SECRET_NAME}`)
    })

    it.each([
        ['the API server fails', 500],
        ['RBAC denies the read', 403],
    ])('reads nothing when %s', async (_label, status) => {
        const { api, url } = await fakeApi({ [KEY]: 'sec' })
        api.listStatus = status
        const source = await kubernetesSource(url)

        expect(await source.read()).toBeNull()
    })

    it('watches from the listed resourceVersion and pushes each change', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        const source = await kubernetesSource(url)
        await source.read()

        const pushed: (SecretSnapshot | null)[] = []
        source.watch((snapshot) => pushed.push(snapshot))
        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)

        const query = api.openWatch?.query
        expect(query?.get('resourceVersion')).toBe('100')
        expect(query?.get('fieldSelector')).toBe(`metadata.name=${SECRET_NAME}`)
        expect(query?.get('allowWatchBookmarks')).toBe('true')

        api.send('MODIFIED', secretObject('101', { [KEY]: 'two' }))
        await vi.waitFor(() => expect(pushed).toEqual([{ values: { [KEY]: 'two' }, revision: '101' }]), WAIT)
    })

    it('reconnects from the last resourceVersion when the watch closes, without listing again', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        const source = await kubernetesSource(url)
        await source.read()
        source.watch(() => {})
        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)

        // A bookmark moves the resourceVersion forward without a change to the secret.
        api.send('BOOKMARK', { metadata: { resourceVersion: '150' } })
        await new Promise((resolve) => setImmediate(resolve))
        api.openWatch?.res.end()

        await vi.waitFor(() => expect(api.watches).toHaveLength(2), WAIT)
        expect(api.watches[1]?.query.get('resourceVersion')).toBe('150')
        expect(api.lists).toHaveLength(1)
        expect(await restarts('closed')).toBe(1)
    })

    it.each([
        ['an ERROR event with code 410', 'event'],
        ['an HTTP 410 on connect', 'status'],
    ])('lists again and watches from the new resourceVersion after %s', async (_label, how) => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        const source = await kubernetesSource(url)
        await source.read()
        if (how === 'status') {
            api.watchStatuses.push(410)
        }
        const pushed: (SecretSnapshot | null)[] = []
        source.watch((snapshot) => pushed.push(snapshot))

        if (how === 'event') {
            await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)
            api.send('ERROR', { kind: 'Status', code: 410, reason: 'Expired' })
        }
        api.secret = { resourceVersion: '205', data: { [KEY]: 'two' } }
        api.listResourceVersion = '210'

        await vi.waitFor(() => expect(api.openWatch?.query.get('resourceVersion')).toBe('210'), WAIT)
        expect(api.lists).toHaveLength(2)
        expect(pushed).toEqual([{ values: { [KEY]: 'two' }, revision: '205' }])
        expect(await restarts('gone')).toBe(1)
    })

    it('backs off and retries when the watch cannot connect', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        api.watchStatuses.push(500, 500)
        const source = await kubernetesSource(url)
        await source.read()
        source.watch(() => {})

        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)
        expect(api.watches).toHaveLength(3)
        expect(api.openWatch?.query.get('resourceVersion')).toBe('100')
        expect(await restarts('error')).toBe(2)
    })

    it('reads the token file again for every request and watch connection', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        const file = await tokenFile('token-1')
        const source = await kubernetesSource(url, file)

        await source.read()
        source.watch(() => {})
        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)

        // Kubelet rotates the projected token in place.
        await writeFile(file, 'token-2\n')
        await source.read()
        api.openWatch?.res.end()
        await vi.waitFor(() => expect(api.watches).toHaveLength(2), WAIT)

        expect(api.lists.map((r) => r.auth)).toEqual(['Bearer token-1', 'Bearer token-2'])
        expect(api.watches.map((r) => r.auth)).toEqual(['Bearer token-1', 'Bearer token-2'])
    })

    // A watch can hang without an error. The safety read is what notices, and it must
    // replace the watch instead of leaving it stalled until the next change.
    it('replaces a watch that missed a change the safety read found', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        const source = await kubernetesSource(url)
        await source.read()
        source.watch(() => {})
        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)

        api.secret = { resourceVersion: '300', data: { [KEY]: 'two' } }
        api.listResourceVersion = '301'
        expect(await source.read()).toEqual({ values: { [KEY]: 'two' }, revision: '300' })

        await vi.waitFor(() => expect(api.openWatch?.query.get('resourceVersion')).toBe('301'), WAIT)
        expect(api.watches[0]?.closed).toBe(true)
        expect(await restarts('stalled')).toBe(1)
    })

    // The list started before the watch delivered a change, so its body is older. Returning
    // it would briefly undo the change, e.g. bring back a signing key a revocation removed.
    it('does not let a slower safety read undo a change the watch delivered', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'old' })
        const source = await kubernetesSource(url)
        await source.read()
        source.watch(() => {})
        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)

        let release!: () => void
        api.holdLists = new Promise((resolve) => {
            release = resolve
        })
        const reading = source.read()
        await vi.waitFor(() => expect(api.lists).toHaveLength(2), WAIT)
        api.send('MODIFIED', secretObject('400', { [KEY]: 'new' }))
        await new Promise((resolve) => setTimeout(resolve, 10))
        release()

        expect(await reading).toEqual({ values: { [KEY]: 'new' }, revision: '400' })
    })

    it('discards a re-list after a 410 that a safety read overtook', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        const source = await kubernetesSource(url)
        await source.read()
        api.watchStatuses.push(410)
        let release!: () => void
        api.holdNextList = new Promise((resolve) => {
            release = resolve
        })
        const pushed: (SecretSnapshot | null)[] = []
        source.watch((snapshot) => pushed.push(snapshot))
        await vi.waitFor(() => expect(api.lists).toHaveLength(2), WAIT)

        api.secret = { resourceVersion: '500', data: { [KEY]: 'two' } }
        api.listResourceVersion = '501'
        expect(await source.read()).toEqual({ values: { [KEY]: 'two' }, revision: '500' })
        release()

        await vi.waitFor(() => expect(api.openWatch?.query.get('resourceVersion')).toBe('501'), WAIT)
        expect(pushed).toEqual([])
    })

    it('closes the watch and stops reconnecting once stopped', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'one' })
        const source = await kubernetesSource(url)
        await source.read()
        source.watch(() => {})
        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)

        source.stop()

        await vi.waitFor(() => expect(api.watches[0]?.closed).toBe(true), WAIT)
        await new Promise((resolve) => setTimeout(resolve, 20))
        expect(api.watches).toHaveLength(1)
        expect(api.lists).toHaveLength(1)
    })
})

describe('credentials server on the kubernetes source', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    function config(): Config {
        return {
            port: 0,
            host: '127.0.0.1',
            shutdownPrestopDelayMs: 0,
            env: 'test',
            mountDir: '/nonexistent/mount',
            reloadSeconds: 3600,
            metricsPort: 0,
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

    async function boot(apiUrl: string): Promise<{
        server: CredentialsServer
        resolve: (signingKey: string) => Promise<Response>
    }> {
        let fetch!: (req: Request) => Response | Promise<Response>
        const server = new CredentialsServer(config(), {
            source: await kubernetesSource(apiUrl),
            serve: (options) => {
                fetch = options.fetch as typeof fetch
                return { close: (cb) => cb() }
            },
            exit: () => {},
        })
        await server.start()
        cleanups.push(() => server.stop('SIGTERM'))
        const resolve = async (signingKey: string): Promise<Response> =>
            await fetch(
                new Request('http://svc/v1/secrets/resolve', {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${await mint(signingKey)}` },
                })
            )
        return { server, resolve }
    }

    // One edit of the secret can revoke a caller and rotate a credential. Both must come
    // from the same snapshot, so the revoked caller never reads the new value.
    it('applies a signing-key revocation and a credential change from one watch event', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'value-1', __CALLER_KEY_TEST_DEPLOYMENT: SIGNING_KEY })
        const { server, resolve } = await boot(url)

        expect(server.lifecycleState().ready).toBe(true)
        expect(await (await resolve(SIGNING_KEY)).json()).toMatchObject({ secrets: { [KEY]: { value: 'value-1' } } })

        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)
        api.send('MODIFIED', secretObject('101', { [KEY]: 'value-2', __CALLER_KEY_TEST_DEPLOYMENT: NEW_SIGNING_KEY }))

        await vi.waitFor(async () => expect((await resolve(SIGNING_KEY)).status).toBe(401), WAIT)
        expect(await (await resolve(NEW_SIGNING_KEY)).json()).toMatchObject({
            secrets: { [KEY]: { value: 'value-2' } },
        })
    })

    it('stays not-ready while the API server is down at boot, then becomes ready', async () => {
        const { api, url } = await fakeApi({ [KEY]: 'value-1', __CALLER_KEY_TEST_DEPLOYMENT: SIGNING_KEY })
        api.listStatus = 503
        const { server, resolve } = await boot(url)

        expect(server.lifecycleState().ready).toBe(false)
        expect((await resolve(SIGNING_KEY)).status).toBe(401)

        api.listStatus = 200
        await vi.waitFor(() => expect(server.lifecycleState().ready).toBe(true), WAIT)
        expect((await resolve(SIGNING_KEY)).status).toBe(200)
    })

    it.each([
        ['the secret is deleted', 'deleted'],
        ['the API server is down at the safety read', 'down'],
    ])('keeps serving what it holds when %s, and says so on the metrics', async (_label, how) => {
        const { api, url } = await fakeApi({ [KEY]: 'value-1', __CALLER_KEY_TEST_DEPLOYMENT: SIGNING_KEY })
        const { server, resolve } = await boot(url)
        await vi.waitFor(() => expect(api.openWatch).toBeDefined(), WAIT)
        // Only Date is faked, so the sockets and the watch keep real timers.
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(Date.now() + 60 * 60 * 1000)

        if (how === 'deleted') {
            api.send('DELETED', secretObject('500', { [KEY]: 'value-1' }))
            await vi.waitFor(async () => expect((await mountErrorsTotal.get()).values[0]?.value).toBe(1), WAIT)
        } else {
            api.listStatus = 500
            await server.reload()
            expect((await mountErrorsTotal.get()).values[0]?.value).toBe(1)
        }

        expect(server.lifecycleState().ready).toBe(true)
        expect(await (await resolve(SIGNING_KEY)).json()).toMatchObject({ secrets: { [KEY]: { value: 'value-1' } } })
        expect(Math.round((await servingStaleSeconds.get()).values[0]?.value ?? 0)).toBe(3600)
    })
})
