/**
 * HACK — short-lived per-session timeline buffer in Redis, used to feed the
 * management UI a live tail of what the agent is doing (assistant messages,
 * tool calls, tool results, errors, raw runner log lines).
 *
 * NOT the long-term shape. The real version will hook into our existing log
 * aggregation (loki / clickhouse) and the UI will hit that directly. This
 * exists so we can ship a usable session inspector now without that
 * pipeline being built. Owns:
 *
 *   - Redis LIST   `session_logs:<id>`       RPUSH line by line, capped via
 *                                            LTRIM(-MAX_BUFFERED, -1)
 *   - Redis TTL    1h after last write       old sessions self-clean
 *   - Pub/sub channel `session_logs:<id>:stream` — every entry is published
 *     so the janitor SSE endpoint can tail in real time
 *
 * Entries are a discriminated union — either a structured `SessionEvent`
 * (same shape `/listen` publishes today; covers assistant messages + tool
 * calls + tool results + completion / failure) or a raw runner log line
 * (`{kind:'log', level, message, extra?}`).
 */
import Redis from 'ioredis'

import { logger } from '../logger'
import type { SessionEvent } from '../pubsub/types'

const KEY_PREFIX = 'session_logs:'
const STREAM_SUFFIX = ':stream'
const TTL_SECONDS = 60 * 60
const MAX_BUFFERED = 1_000

export type SessionLogEntry =
    | ({ kind: 'event' } & SessionEvent)
    | {
          kind: 'log'
          at: string
          level: 'debug' | 'info' | 'warn' | 'error'
          message: string
          extra?: Record<string, unknown>
      }

export interface SessionLogStore {
    append(sessionId: string, entry: SessionLogEntry): Promise<void>
    getBuffered(sessionId: string): Promise<SessionLogEntry[]>
    subscribe(sessionId: string, listener: (entry: SessionLogEntry) => void): Promise<() => Promise<void>>
    disconnect(): Promise<void>
}

export class RedisSessionLogStore implements SessionLogStore {
    private readonly publisher: Redis.Redis
    private readonly subscriber: Redis.Redis
    private readonly listeners = new Map<string, Set<(entry: SessionLogEntry) => void>>()
    private readonly seenSessions = new Set<string>()

    constructor(config: { url: string }) {
        this.publisher = new Redis(config.url)
        this.subscriber = new Redis(config.url)
        this.subscriber.on('message', (channel: string, raw: string) => {
            const set = this.listeners.get(channel)
            if (!set) {
                return
            }
            let entry: SessionLogEntry
            try {
                entry = JSON.parse(raw) as SessionLogEntry
            } catch (err) {
                logger.error('SessionLogStore: bad message on stream', { channel, error: String(err) })
                return
            }
            for (const listener of set) {
                try {
                    listener(entry)
                } catch (err) {
                    logger.error('SessionLogStore listener threw', { channel, error: String(err) })
                }
            }
        })
    }

    async append(sessionId: string, entry: SessionLogEntry): Promise<void> {
        const key = KEY_PREFIX + sessionId
        const channel = key + STREAM_SUFFIX
        const payload = JSON.stringify(entry)
        // Three writes, independent: RPUSH + LTRIM + EXPIRE (atomic in one
        // MULTI), and the PUBLISH for live tailers.
        const [multiResult] = await Promise.all([
            this.publisher.multi().rpush(key, payload).ltrim(key, -MAX_BUFFERED, -1).expire(key, TTL_SECONDS).exec(),
            this.publisher.publish(channel, payload),
        ])
        if (!this.seenSessions.has(sessionId)) {
            this.seenSessions.add(sessionId)
            logger.info('SessionLogStore: first append for session', {
                sessionId,
                kind: entry.kind,
                type: entry.kind === 'event' ? entry.type : entry.level,
            })
        }
        // ioredis returns Array<[Error|null, unknown]> from multi().exec().
        // Surface any per-command failure so silent breakage is visible.
        const failed = (multiResult ?? []).filter(([err]) => err != null)
        if (failed.length > 0) {
            logger.warn('SessionLogStore: redis multi reported errors', {
                sessionId,
                errors: failed.map(([err]) => String(err)),
            })
        }
    }

    async getBuffered(sessionId: string): Promise<SessionLogEntry[]> {
        const key = KEY_PREFIX + sessionId
        const raw = await this.publisher.lrange(key, 0, -1)
        const out: SessionLogEntry[] = []
        for (const r of raw) {
            try {
                out.push(JSON.parse(r) as SessionLogEntry)
            } catch {
                // Drop malformed entries — best-effort buffer.
            }
        }
        return out
    }

    async subscribe(sessionId: string, listener: (entry: SessionLogEntry) => void): Promise<() => Promise<void>> {
        const channel = KEY_PREFIX + sessionId + STREAM_SUFFIX
        let set = this.listeners.get(channel)
        if (!set) {
            set = new Set()
            this.listeners.set(channel, set)
            await this.subscriber.subscribe(channel)
        }
        set.add(listener)
        return async () => {
            const current = this.listeners.get(channel)
            if (!current) {
                return
            }
            current.delete(listener)
            if (current.size === 0) {
                this.listeners.delete(channel)
                await this.subscriber.unsubscribe(channel)
            }
        }
    }

    async disconnect(): Promise<void> {
        this.listeners.clear()
        await this.publisher.quit()
        await this.subscriber.quit()
    }
}

/**
 * No-op implementation. The runner uses this when no Redis URL is configured
 * (matches the existing InMemorySessionBus fallback). Append is a black hole;
 * getBuffered returns empty; subscribe never fires. Lets local-process dev
 * stacks keep working without a Redis dep.
 */
export class NullSessionLogStore implements SessionLogStore {
    async append(): Promise<void> {
        /* no-op */
    }
    async getBuffered(): Promise<SessionLogEntry[]> {
        return []
    }
    async subscribe(): Promise<() => Promise<void>> {
        return async () => {
            /* no-op */
        }
    }
    async disconnect(): Promise<void> {
        /* no-op */
    }
}
