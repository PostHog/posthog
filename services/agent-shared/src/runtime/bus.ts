/**
 * Session event bus. Production wires to Redis pub/sub; tests use the
 * in-memory impl below. Carries lifecycle events from the runner to listening
 * clients (chat /listen, MCP transport, future telemetry sinks).
 */

import type { Redis as IoRedis } from 'ioredis'

import { createLogger } from './logger'

export type SessionEventKind =
    | 'session_started'
    | 'turn_started'
    | 'assistant_text'
    | 'tool_call'
    | 'tool_result'
    | 'completed'
    | 'waiting'
    | 'failed'

export interface SessionEvent {
    session_id: string
    kind: SessionEventKind
    data: Record<string, unknown>
    ts: string
}

export interface SessionEventBus {
    publish(event: SessionEvent): Promise<void>
    subscribe(sessionId: string, fn: (e: SessionEvent) => void): () => void
}

export class MemorySessionEventBus implements SessionEventBus {
    private readonly subs = new Map<string, Set<(e: SessionEvent) => void>>()

    async publish(event: SessionEvent): Promise<void> {
        const set = this.subs.get(event.session_id)
        if (!set) {
            return
        }
        for (const fn of set) {
            try {
                fn(event)
            } catch {
                // ignore subscriber errors so one bad listener doesn't break others
            }
        }
    }

    subscribe(sessionId: string, fn: (e: SessionEvent) => void): () => void {
        let set = this.subs.get(sessionId)
        if (!set) {
            set = new Set()
            this.subs.set(sessionId, set)
        }
        set.add(fn)
        return () => {
            set!.delete(fn)
            if (set!.size === 0) {
                this.subs.delete(sessionId)
            }
        }
    }
}

/** A no-op bus — drop events on the floor. Useful for production runners
 *  that don't have a bus wired yet. */
export class NoopSessionEventBus implements SessionEventBus {
    async publish(_event: SessionEvent): Promise<void> {
        // intentionally empty
    }
    subscribe(_sessionId: string, _fn: (e: SessionEvent) => void): () => void {
        return () => undefined
    }
}

/* -------------------------------------------------------------------------- */
/* Redis pub/sub — production bus across runner ↔ ingress processes.          */
/* -------------------------------------------------------------------------- */

export interface RedisSessionEventBusOptions {
    /** ioredis-compatible URL, e.g. `redis://localhost:6379`. */
    url: string
    /**
     * Channel prefix. Defaults to `agent_session`. Distinct from v1's
     * `agent_session:` so a co-tenant v1 deployment doesn't see v2 events.
     */
    channelPrefix?: string
}

/**
 * Redis-backed bus for cross-process fan-out — ingress /listen SSE clients
 * connected to host A receive events from runners on host B.
 *
 * Two connections: one for `PUBLISH`, one for `SUBSCRIBE` (ioredis enters a
 * dedicated subscriber state on the connection that issues SUBSCRIBE, so it
 * can't be reused for arbitrary commands). Subscriptions are ref-counted by
 * channel so subscribing N listeners to one session only opens one Redis
 * channel.
 *
 * Lazy-imports `ioredis` so the v2 packages don't pull it in for dev / tests
 * that use `MemorySessionEventBus`. Call `await bus.connect()` once at boot;
 * `disconnect()` on shutdown.
 */
export class RedisSessionEventBus implements SessionEventBus {
    private readonly opts: Required<RedisSessionEventBusOptions>
    private readonly log = createLogger('redis-bus')
    private readonly subs = new Map<string, Set<(e: SessionEvent) => void>>()
    private publisher: IoRedis | null = null
    private subscriber: IoRedis | null = null
    private connectPromise: Promise<void> | null = null

    constructor(opts: RedisSessionEventBusOptions) {
        this.opts = { channelPrefix: 'agent_session', ...opts }
    }

    async connect(): Promise<void> {
        if (this.connectPromise) {
            return this.connectPromise
        }
        this.connectPromise = (async () => {
            const mod = await import('ioredis')
            const Ctor = (mod as { default?: typeof import('ioredis').default }).default ?? mod
            const RedisCtor = Ctor as unknown as new (url: string) => IoRedis
            this.publisher = new RedisCtor(this.opts.url)
            this.subscriber = new RedisCtor(this.opts.url)
            this.subscriber.on('message', (channel: string, message: string) => {
                const sessionId = this.sessionIdFromChannel(channel)
                if (!sessionId) {
                    return
                }
                const set = this.subs.get(sessionId)
                if (!set) {
                    return
                }
                let event: SessionEvent
                try {
                    event = JSON.parse(message) as SessionEvent
                } catch (err) {
                    this.log.warn({ channel, err: (err as Error).message }, 'parse_failed')
                    return
                }
                for (const fn of set) {
                    try {
                        fn(event)
                    } catch (err) {
                        this.log.warn({ channel, err: (err as Error).message }, 'listener_threw')
                    }
                }
            })
        })()
        return this.connectPromise
    }

    async publish(event: SessionEvent): Promise<void> {
        if (!this.publisher) {
            await this.connect()
        }
        await this.publisher!.publish(this.channel(event.session_id), JSON.stringify(event))
    }

    subscribe(sessionId: string, fn: (e: SessionEvent) => void): () => void {
        let set = this.subs.get(sessionId)
        if (!set) {
            set = new Set()
            this.subs.set(sessionId, set)
            // Fire-and-forget — the SUBSCRIBE round-trip is fast, and races
            // are tolerated (the message we miss is at-most one published
            // before the SUBSCRIBE was ACKed; production also tolerates that).
            void this.ensureSubscribed(sessionId)
        }
        set.add(fn)
        return () => {
            const current = this.subs.get(sessionId)
            if (!current) {
                return
            }
            current.delete(fn)
            if (current.size === 0) {
                this.subs.delete(sessionId)
                if (this.subscriber) {
                    void this.subscriber.unsubscribe(this.channel(sessionId)).catch(() => undefined)
                }
            }
        }
    }

    private async ensureSubscribed(sessionId: string): Promise<void> {
        if (!this.subscriber) {
            await this.connect()
        }
        try {
            await this.subscriber!.subscribe(this.channel(sessionId))
        } catch (err) {
            this.log.error({ session_id: sessionId, err: (err as Error).message }, 'subscribe_failed')
        }
    }

    async disconnect(): Promise<void> {
        this.subs.clear()
        const closers: Promise<unknown>[] = []
        if (this.subscriber) {
            closers.push(this.subscriber.quit().catch(() => undefined))
            this.subscriber = null
        }
        if (this.publisher) {
            closers.push(this.publisher.quit().catch(() => undefined))
            this.publisher = null
        }
        await Promise.all(closers)
        this.connectPromise = null
    }

    private channel(sessionId: string): string {
        return `${this.opts.channelPrefix}:${sessionId}`
    }

    private sessionIdFromChannel(channel: string): string | null {
        const prefix = `${this.opts.channelPrefix}:`
        return channel.startsWith(prefix) ? channel.slice(prefix.length) : null
    }
}
