/**
 * LogSink — the runner's structured-log out-bound. Each session lifecycle
 * event becomes a row in the team's `log_entries` ClickHouse table.
 *
 * Three impls:
 *   - InMemoryLogSink (tests + local dev) — captures entries for assertion
 *   - NoopLogSink (production runners that haven't wired logs yet)
 *   - ClickHouseLogSink (prod, via Kafka → CH; placeholder below)
 *
 * Schema mirrors the v1 `log_entries` table shape so an eventual migration is
 * a straight rename. The runner publishes one entry per lifecycle event;
 * downstream materialized views in ClickHouse aggregate by team / session /
 * level / event.
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogEntry {
    /** Time the event happened, ISO-8601. */
    ts: string
    team_id: number
    application_id: string
    session_id: string
    level: LogLevel
    /** Stable event name, e.g. "session_started", "tool_called", "session_failed". */
    event: string
    /** Free-form structured data. ClickHouse stores it as JSON. */
    data: Record<string, unknown>
}

export interface LogSink {
    write(entries: LogEntry[]): Promise<void>
}

export class InMemoryLogSink implements LogSink {
    public readonly entries: LogEntry[] = []

    async write(entries: LogEntry[]): Promise<void> {
        this.entries.push(...entries)
    }

    /** Return entries filtered by session. Most tests want this. */
    forSession(sessionId: string): LogEntry[] {
        return this.entries.filter((e) => e.session_id === sessionId)
    }

    clear(): void {
        this.entries.length = 0
    }
}

export class NoopLogSink implements LogSink {
    async write(_entries: LogEntry[]): Promise<void> {
        // intentionally empty
    }
}

/**
 * Placeholder for the real ClickHouse sink. Production writes via Kafka — the
 * client lib + the topic schema are out of scope here. Wire this up when the
 * pipeline lands; the interface above stays the same.
 */
export class ClickHouseLogSink implements LogSink {
    constructor(_opts: { kafkaBrokers: string; topic: string }) {
        // TODO: actually push to Kafka here.
    }

    async write(_entries: LogEntry[]): Promise<void> {
        throw new Error('ClickHouseLogSink not implemented — wire Kafka and CH first')
    }
}
