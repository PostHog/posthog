/**
 * Per-session writer that turns `SessionEvent` / `log` entries into flat
 * `LogEntry` rows for the Kafka producer.
 *
 * The agent runtime emits events in the `SessionEvent` union shape (see
 * ../pubsub/types). This logger formats each event into a human-readable
 * `[kind] line` string and writes it to the shared producer.
 */
import type { SessionEvent } from '../pubsub/types'
import type { LogProducer } from './producer'
import { AGENT_SESSION_LOG_SOURCE, type LogEntry, type LogLevel } from './types'

/**
 * Event types that are streamed to live listeners but never persisted. A
 * streamed answer is hundreds–thousands of `message_delta` events — writing
 * them to ClickHouse would explode `log_entries`. The durable record is the
 * final complete `message`; deltas are a pure live-view side channel.
 */
const EPHEMERAL_EVENT_TYPES = new Set<SessionEvent['type']>(['message_delta'])

export interface SessionLoggerOptions {
    teamId: number
    /**
     * AgentApplication UUID (string form). `null` is tolerated for legacy /
     * orphan jobs that have no application bound — in that case the logger
     * silently drops writes (so callers don't have to special-case it). This
     * keeps the surface non-optional downstream.
     */
    applicationId: string | null
    /** Session UUID (string form). */
    sessionId: string
    producer: LogProducer
    /** Override timestamp source (tests). */
    now?: () => Date
}

export interface SessionLogger {
    /** Format a `SessionEvent` to a `[kind] line` row and write it. */
    appendEvent(event: SessionEvent): void
    /** Free-form log line. Levels: 'info' default; 'error' becomes [error]. */
    appendLog(opts: { level?: LogLevel; message: string }): void
}

export function createSessionLogger(opts: SessionLoggerOptions): SessionLogger {
    const now = opts.now ?? (() => new Date())
    const applicationId = opts.applicationId
    const write = (level: LogLevel, message: string, at?: string): void => {
        if (!applicationId) {
            return // orphan job — drop the row rather than emit with a null log_source_id
        }
        const entry: LogEntry = {
            team_id: opts.teamId,
            log_source: AGENT_SESSION_LOG_SOURCE,
            log_source_id: applicationId,
            instance_id: opts.sessionId,
            timestamp: at ?? toMicrosecondISO(now()),
            level,
            message,
        }
        opts.producer.append(entry)
    }

    return {
        appendEvent(event: SessionEvent): void {
            // Ephemeral events (streamed token deltas) are never persisted.
            if (EPHEMERAL_EVENT_TYPES.has(event.type)) {
                return
            }
            const [level, message] = formatEvent(event)
            write(level, message, toClickhouseTimestamp(event.at))
        },
        appendLog({ level = 'INFO', message }): void {
            const prefix = level === 'ERROR' ? '[error]' : '[meta]'
            write(level, `${prefix} ${message}`)
        },
    }
}

/**
 * Format a `SessionEvent` to `[level, message]` per the prefix vocabulary
 * locked in the spec. Kept exported for unit testing the line shape.
 */
export function formatEvent(event: SessionEvent): [LogLevel, string] {
    switch (event.type) {
        case 'turn_started':
            return ['INFO', '[event] turn_started']
        case 'turn_completed':
            return ['INFO', '[event] turn_completed']
        case 'message':
            return ['INFO', `[chat] ${event.role}: ${oneLine(event.content)}`]
        case 'message_delta':
            // Unreachable: appendEvent drops ephemeral events before formatting.
            // The case exists only to keep this switch exhaustive.
            return ['INFO', `[chat] delta: ${oneLine(event.text)}`]
        case 'tool_call': {
            const args = event.args === undefined ? '' : ` args=${truncate(stringifyArgs(event.args), 300)}`
            return ['INFO', `[tool] ${event.tool}${args}`]
        }
        case 'tool_result': {
            if (event.ok) {
                const result = event.result === undefined ? '' : ` result=${truncate(stringifyArgs(event.result), 300)}`
                return ['INFO', `[tool] ${event.tool} → ok${result}`]
            }
            const err = event.error ? `: ${event.error}` : ''
            return ['ERROR', `[error] ${event.tool} failed${err}`]
        }
        case 'status':
            return ['INFO', `[meta] status: ${oneLine(event.text)}`]
        case 'awaiting_input': {
            const prompt = event.prompt ? ` prompt=${oneLine(event.prompt)}` : ''
            return ['INFO', `[meta] awaiting_input${prompt}`]
        }
        case 'session_completed':
            return ['INFO', '[event] session_completed']
        case 'session_failed':
            return ['ERROR', `[error] session_failed: ${event.error}`]
    }
}

/** Collapse newlines so each log line stays on a single CH row. */
function oneLine(s: string): string {
    return s.replace(/\s*\n+\s*/g, ' ').trim()
}

function stringifyArgs(value: unknown): string {
    try {
        return typeof value === 'string' ? value : JSON.stringify(value)
    } catch {
        return String(value)
    }
}

function truncate(s: string, max: number): string {
    if (s.length <= max) {
        return s
    }
    return `${s.slice(0, max - 1)}…`
}

/**
 * `DateTime64(6, 'UTC')` accepts space-separated `YYYY-MM-DD HH:MM:SS.ffffff`
 * — the same shape the existing CDP `log_entries` producer uses. Strict ISO
 * with `T`/`Z` is silently dropped by ClickHouse's Kafka-engine consumer
 * (it has `kafka_skip_broken_messages = 100`). JS Dates are ms-resolution;
 * pad three zeros for the microsecond field.
 */
function toMicrosecondISO(d: Date): string {
    return toClickhouseTimestamp(d.toISOString())
}

function toClickhouseTimestamp(input: string): string {
    return input
        .replace('T', ' ')
        .replace(/\.(\d{3})Z$/, '.$1000')
        .replace(/Z$/, '')
}
