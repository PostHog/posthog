// Reads the Kubernetes Secret through the API server with a watch, instead of through a
// mounted volume. Kubelet refreshes a mounted Secret on each node on its own schedule, so
// replicas served different versions for a minute or more after an edit. A watch delivers
// the edit to every replica within about a second of External Secrets Operator writing it.
//
// A small client on node:http(s) instead of @kubernetes/client-node, to keep this service's
// dependency tree small. RBAC grants get/list/watch on this one Secret through
// `resourceNames`, which only authorizes a list or watch that carries
// `fieldSelector=metadata.name=<name>`.

import { readFile } from 'node:fs/promises'
import http, { type IncomingMessage } from 'node:http'
import https from 'node:https'

import type { KubernetesSourceConfig } from './lib/config'
import { logger } from './lib/logging'
import { secretWatchRestartsTotal } from './metrics'
import type { SecretSnapshot, SecretSource, SnapshotListener } from './source'

/** A list that sends nothing for this long has hung, and the read fails. */
const REQUEST_IDLE_TIMEOUT_MS = 10_000

// The API server sends a bookmark on an idle watch about once a minute, so a watch that sends
// nothing for much longer is a dead connection that never closed.
const WATCH_IDLE_TIMEOUT_MS = 5 * 60_000

/** Why a watch connection ended. A metric label, so keep the set small and stable. */
type WatchEnd = 'closed' | 'gone' | 'error' | 'idle' | 'stalled' | 'stopped'

interface SecretObject {
    metadata?: { name?: string; resourceVersion?: string }
    data?: Record<string, string> | null
}

interface SecretList {
    metadata?: { resourceVersion?: string }
    items?: SecretObject[]
}

interface WatchEvent {
    type?: string
    object?: SecretObject & { code?: number }
}

interface Listed {
    snapshot: SecretSnapshot | null
    resourceVersion: string
}

export interface KubernetesSecretSourceOptions extends KubernetesSourceConfig {
    backoff?: { initialMs: number; maxMs: number }
}

function errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
}

export class KubernetesSecretSource implements SecretSource {
    readonly kind = 'kubernetes'
    readonly description: string

    private readonly agent: http.Agent
    private readonly backoff: { initialMs: number; maxMs: number }
    private listener: SnapshotListener | null = null
    private stopped = false
    /** Where the next watch starts. Null means list first. */
    private resourceVersion: string | null = null
    /** The newest snapshot this source has produced. */
    private latest: SecretSnapshot | null = null
    /** Counts snapshots applied by the watch or a safety read, so a list can tell that one landed while it ran. */
    private changes = 0
    private endActiveWatch: ((reason: WatchEnd) => void) | null = null
    private readonly inFlight = new Set<AbortController>()
    private cancelSleep: (() => void) | null = null

    constructor(private readonly opts: KubernetesSecretSourceOptions) {
        this.description = `kubernetes secret ${opts.namespace}/${opts.secretName}`
        this.backoff = opts.backoff ?? { initialMs: 500, maxMs: 30_000 }
        // The pods carry HTTP_PROXY/HTTPS_PROXY for the egress proxy, and NO_PROXY may not be
        // widened. An agent built without `proxyEnv` never reads those variables, even under
        // NODE_USE_ENV_PROXY, so the API server is always reached directly.
        this.agent = new URL(opts.apiUrl).protocol === 'https:' ? new https.Agent() : new http.Agent()
    }

    async read(): Promise<SecretSnapshot | null> {
        const changesBefore = this.changes
        let listed: Listed
        try {
            listed = await this.list()
        } catch (err) {
            logger.warn('source:read_failed', { source: this.description, error: errorMessage(err) })
            return null
        }

        if (this.changes !== changesBefore) {
            // The watch delivered a change while this list was in flight, so the list result
            // can be older than what the watch delivered. Returning it would briefly undo that
            // change, for example bring back a revoked signing key.
            return this.latest
        }

        if (this.endActiveWatch && listed.snapshot?.revision !== this.latest?.revision) {
            // A live watch should have delivered this change already. It has stalled without an
            // error, so replace it with a watch that starts from this list.
            this.resourceVersion = listed.resourceVersion
            this.endActiveWatch('stalled')
        } else if (!this.endActiveWatch) {
            this.resourceVersion = listed.resourceVersion
        }
        this.changes++
        this.latest = listed.snapshot
        return listed.snapshot
    }

    watch(listener: SnapshotListener): void {
        if (this.listener || this.stopped) {
            return
        }
        this.listener = listener
        this.run().catch((err: unknown) => {
            logger.error('source:watch_crashed', { source: this.description, error: errorMessage(err) })
        })
    }

    stop(): void {
        this.stopped = true
        this.endActiveWatch?.('stopped')
        for (const controller of this.inFlight) {
            controller.abort()
        }
        this.cancelSleep?.()
    }

    private async run(): Promise<void> {
        // Restarts in a row whose watch delivered nothing. The first restart after a working
        // watch is immediate. A run of watches that end without events backs off, so a broken
        // API server does not get a tight reconnect loop.
        let quietRestarts = 0

        while (!this.stopped) {
            if (this.resourceVersion === null) {
                const changesBefore = this.changes
                let listed: Listed
                try {
                    listed = await this.list()
                } catch (err) {
                    if (this.stopped) {
                        return
                    }
                    const delayMs = this.backoffMs(quietRestarts++)
                    logger.warn('source:list_failed', { source: this.description, error: errorMessage(err), delayMs })
                    await this.sleep(delayMs)
                    continue
                }
                if (this.changes !== changesBefore) {
                    // A safety read or a watch event applied a snapshot while this list was in
                    // flight, so this list can be older. Publishing it could bring back a
                    // revoked key. Start over from whatever that snapshot left behind.
                    continue
                }
                this.resourceVersion = listed.resourceVersion
                this.publish(listed.snapshot)
            }

            const { reason, sawEvents } = await this.watchOnce(this.resourceVersion)
            if (reason === 'stopped' || this.stopped) {
                return
            }
            if (reason === 'gone') {
                this.resourceVersion = null
            }

            quietRestarts = sawEvents ? 0 : quietRestarts + 1
            const delayMs =
                reason !== 'error' && quietRestarts <= 1 ? 0 : this.backoffMs(Math.max(quietRestarts - 1, 0))
            secretWatchRestartsTotal.labels({ reason }).inc()
            logger.info('source:watch_restart', {
                source: this.description,
                reason,
                resourceVersion: this.resourceVersion,
                delayMs,
            })
            if (delayMs > 0) {
                await this.sleep(delayMs)
            }
        }
    }

    private backoffMs(attempt: number): number {
        return Math.min(this.backoff.initialMs * 2 ** attempt, this.backoff.maxMs)
    }

    private sleep(ms: number): Promise<void> {
        return new Promise((resolve) => {
            const timer = setTimeout(() => {
                this.cancelSleep = null
                resolve()
            }, ms)
            this.cancelSleep = () => {
                clearTimeout(timer)
                this.cancelSleep = null
                resolve()
            }
        })
    }

    private publish(snapshot: SecretSnapshot | null): void {
        this.changes++
        this.latest = snapshot
        this.listener?.(snapshot)
    }

    private snapshotOf(object: SecretObject | undefined): SecretSnapshot {
        const values: Record<string, string> = {}
        for (const [key, encoded] of Object.entries(object?.data ?? {})) {
            // Same rules as the mount reader, so both sources hash the same content to the
            // same version id: skip dot-prefixed entries and trim what a human left behind.
            if (!key.startsWith('.')) {
                values[key] = Buffer.from(encoded, 'base64').toString('utf8').trim()
            }
        }
        return { values, revision: object?.metadata?.resourceVersion ?? null }
    }

    private async list(): Promise<Listed> {
        const controller = this.track(new AbortController())
        try {
            const res = await this.open(new URLSearchParams({ fieldSelector: this.fieldSelector() }), controller, null)
            const body = (await readJson(res)) as SecretList
            const resourceVersion = body.metadata?.resourceVersion
            if (!resourceVersion) {
                throw new Error('list response has no resourceVersion')
            }
            const item = body.items?.find((candidate) => candidate.metadata?.name === this.opts.secretName)
            if (!item) {
                logger.error('source:secret_missing', { source: this.description })
            }
            return { snapshot: item ? this.snapshotOf(item) : null, resourceVersion }
        } finally {
            this.inFlight.delete(controller)
        }
    }

    private async watchOnce(resourceVersion: string): Promise<{ reason: WatchEnd; sawEvents: boolean }> {
        const controller = this.track(new AbortController())
        let ended: WatchEnd | null = null
        const end = (reason: WatchEnd): void => {
            if (ended === null) {
                ended = reason
                controller.abort()
            }
        }
        this.endActiveWatch = end

        try {
            let res: IncomingMessage
            try {
                res = await this.open(
                    new URLSearchParams({
                        watch: '1',
                        fieldSelector: this.fieldSelector(),
                        resourceVersion,
                        allowWatchBookmarks: 'true',
                    }),
                    controller,
                    () => end('idle')
                )
            } catch (err) {
                if (ended === null) {
                    logger.warn('source:watch_failed', { source: this.description, error: errorMessage(err) })
                }
                return { reason: ended ?? 'error', sawEvents: false }
            }

            if (res.statusCode !== 200) {
                res.resume()
                logger.warn('source:watch_rejected', { source: this.description, status: res.statusCode })
                return { reason: res.statusCode === 410 ? 'gone' : 'error', sawEvents: false }
            }

            return await new Promise((resolve) => {
                let buffer = ''
                let sawEvents = false
                let settled = false
                const finish = (reason: WatchEnd): void => {
                    if (!settled) {
                        settled = true
                        end(reason)
                        resolve({ reason: ended ?? reason, sawEvents })
                    }
                }

                res.setEncoding('utf8')
                res.on('data', (chunk: string) => {
                    buffer += chunk
                    let newline = buffer.indexOf('\n')
                    while (newline >= 0 && ended === null) {
                        const line = buffer.slice(0, newline).trim()
                        buffer = buffer.slice(newline + 1)
                        newline = buffer.indexOf('\n')
                        if (!line) {
                            continue
                        }
                        sawEvents = true
                        const outcome = this.handleEvent(line)
                        if (outcome) {
                            finish(outcome)
                        }
                    }
                })
                res.on('end', () => finish('closed'))
                res.on('error', (err) => {
                    logger.warn('source:watch_stream_failed', { source: this.description, error: errorMessage(err) })
                    finish('error')
                })
                res.on('close', () => finish('closed'))
            })
        } finally {
            this.inFlight.delete(controller)
            if (this.endActiveWatch === end) {
                this.endActiveWatch = null
            }
        }
    }

    /** Apply one watch event. Returns why the watch must end, or null to keep reading. */
    private handleEvent(line: string): WatchEnd | null {
        let event: WatchEvent
        try {
            event = JSON.parse(line) as WatchEvent
        } catch {
            logger.warn('source:watch_bad_event', { source: this.description })
            return 'error'
        }

        const resourceVersion = event.object?.metadata?.resourceVersion
        switch (event.type) {
            case 'ADDED':
            case 'MODIFIED':
                if (resourceVersion) {
                    this.resourceVersion = resourceVersion
                }
                this.publish(this.snapshotOf(event.object))
                return null
            case 'BOOKMARK':
                if (resourceVersion) {
                    this.resourceVersion = resourceVersion
                }
                return null
            case 'DELETED':
                if (resourceVersion) {
                    this.resourceVersion = resourceVersion
                }
                // Going empty would fail every resolve, which callers treat as a deleted
                // credential. Keep serving what is held; the staleness gauge and the error
                // counter make the deletion visible.
                logger.error('source:secret_deleted', { source: this.description })
                this.publish(null)
                return null
            case 'ERROR':
                logger.warn('source:watch_error_event', { source: this.description, code: event.object?.code })
                return event.object?.code === 410 ? 'gone' : 'error'
            default:
                return null
        }
    }

    private fieldSelector(): string {
        return `metadata.name=${this.opts.secretName}`
    }

    private track(controller: AbortController): AbortController {
        this.inFlight.add(controller)
        return controller
    }

    /**
     * Open a GET on the namespace's secrets collection. `onIdle` runs when the socket sends
     * nothing for the idle limit. Without it the request fails at the shorter request limit.
     */
    private async open(
        query: URLSearchParams,
        controller: AbortController,
        onIdle: (() => void) | null
    ): Promise<IncomingMessage> {
        const url = new URL(`/api/v1/namespaces/${this.opts.namespace}/secrets?${query.toString()}`, this.opts.apiUrl)
        // The projected token rotates, so a token read at boot expires in a long-lived pod.
        const token = (await readFile(this.opts.tokenFile, 'utf8')).trim()
        const options: https.RequestOptions = {
            method: 'GET',
            agent: this.agent,
            headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
            signal: controller.signal,
        }

        const ca = url.protocol === 'https:' ? await readFile(this.opts.caFile) : null

        return await new Promise<IncomingMessage>((resolve, reject) => {
            const req = ca ? https.request(url, { ...options, ca }, resolve) : http.request(url, options, resolve)
            req.setTimeout(onIdle ? WATCH_IDLE_TIMEOUT_MS : REQUEST_IDLE_TIMEOUT_MS, () => {
                if (onIdle) {
                    onIdle()
                } else {
                    req.destroy(new Error('request timed out'))
                }
            })
            req.on('error', reject)
            req.end()
        })
    }
}

async function readJson(res: IncomingMessage): Promise<unknown> {
    if (res.statusCode !== 200) {
        res.resume()
        throw new Error(`API server answered HTTP ${res.statusCode}`)
    }
    const chunks: Buffer[] = []
    for await (const chunk of res) {
        chunks.push(chunk as Buffer)
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}
