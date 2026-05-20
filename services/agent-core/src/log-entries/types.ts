/**
 * Schema mirror for ClickHouse's `log_entries` table — see
 * posthog/clickhouse/log_entries.py. We reuse CDP's pipeline:
 *
 *   agent-runner ─Kafka─▶ topic: log_entries ─consumer─▶ log_entries (CH)
 *
 * One row per `LogEntry`. `message` is human-readable flat text with a
 * `[meta]` / `[chat]` / `[tool]` / `[event]` / `[error]` prefix; no JSON
 * encoding. See docs/internal/agent-persistent-logs.md.
 */

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

/**
 * Prefix tags rendered into `message`. Lock as an enum so the writer
 * (agent-runner) and downstream renderers (frontend / CLI) agree on
 * the small vocabulary.
 */
export type LogKind = 'meta' | 'chat' | 'tool' | 'event' | 'error'

export const LOG_KIND_BY_PREFIX: Record<string, LogKind> = {
    '[meta]': 'meta',
    '[chat]': 'chat',
    '[tool]': 'tool',
    '[event]': 'event',
    '[error]': 'error',
}

export interface LogEntry {
    team_id: number
    /** `agent_session` for everything emitted in this module. */
    log_source: string
    /** AgentApplication UUID (string form). */
    log_source_id: string
    /** Session UUID (string form). */
    instance_id: string
    /** ISO timestamp with microsecond precision (matches `DateTime64(6, 'UTC')`). */
    timestamp: string
    level: LogLevel
    /** Flat human-readable line with a `[kind]` prefix. */
    message: string
}

/** `log_source` constant for everything this package writes. */
export const AGENT_SESSION_LOG_SOURCE = 'agent_session'
