/**
 * Tiny ClickHouse HTTP client — just enough for the e2e harness to read back
 * the `log_entries` rows the runner produced via Kafka. Uses the HTTP
 * interface so we don't pull in another client lib for one read path.
 *
 * Reads only. Writes go via `KafkaLogProducer` → Kafka → ClickHouse Kafka
 * engine → materialized view → `log_entries` table. The harness asserts on
 * the *result* of that pipeline; nothing here bypasses it.
 */

export interface ClickHouseClientOptions {
    /** HTTP base URL, e.g. `http://localhost:8123`. */
    url: string
    /** Default 'default'; matches the local dev defaults. */
    user?: string
    /** Default '' (no auth in dev). */
    password?: string
    /** Default 'posthog' — where the `log_entries` table lives. */
    database?: string
}

export interface LogEntryRow {
    team_id: number
    log_source: string
    log_source_id: string
    instance_id: string
    timestamp: string
    level: string
    message: string
}

export class ClickHouseClient {
    private readonly url: string
    private readonly auth: { user: string; password: string }
    private readonly database: string

    constructor(opts: ClickHouseClientOptions) {
        this.url = opts.url.replace(/\/$/, '')
        this.auth = { user: opts.user ?? 'default', password: opts.password ?? '' }
        // `log_entries` lives in the `posthog` database in the dev stack; the
        // default `default` database doesn't have it. Override via options
        // for self-hosted setups that put PostHog elsewhere.
        this.database = opts.database ?? process.env.CLICKHOUSE_DATABASE ?? 'posthog'
    }

    /** GET `/ping` — used by the cluster's startup probe. */
    async ping(): Promise<void> {
        const res = await fetch(`${this.url}/ping`, { headers: this.headers() })
        if (!res.ok) {
            throw new Error(`ClickHouse ping returned ${res.status}`)
        }
    }

    /**
     * Run a SELECT query and return JSON rows. `params` are POSTed via the
     * `param_<name>=<value>` query-string convention CH supports for
     * parameterised queries — saves us escaping strings ourselves.
     */
    async query<Row = Record<string, unknown>>(
        sql: string,
        params: Record<string, string | number> = {}
    ): Promise<Row[]> {
        const search = new URLSearchParams()
        search.set('database', this.database)
        for (const [k, v] of Object.entries(params)) {
            search.set(`param_${k}`, String(v))
        }
        // FORMAT JSONEachRow gives us NDJSON we can split + parse.
        const finalSql = /format\s+\w+/i.test(sql) ? sql : `${sql} FORMAT JSONEachRow`
        const res = await fetch(`${this.url}/?${search}`, {
            method: 'POST',
            body: finalSql,
            headers: { ...this.headers(), 'content-type': 'text/plain' },
        })
        if (!res.ok) {
            const detail = await res.text().catch(() => '')
            throw new Error(`ClickHouse query failed (${res.status}): ${detail.slice(0, 500)}`)
        }
        const text = await res.text()
        if (text.trim().length === 0) {
            return []
        }
        return text
            .split('\n')
            .filter((line) => line.length > 0)
            .map((line) => JSON.parse(line) as Row)
    }

    /**
     * Fetch all `log_entries` rows for a session id (`instance_id`). Single
     * query — sorted by timestamp asc.
     */
    async logsForSession(sessionId: string): Promise<LogEntryRow[]> {
        return this.query<LogEntryRow>(
            `SELECT team_id, log_source, log_source_id, instance_id,
                    toString(timestamp) AS timestamp, level, message
             FROM log_entries
             WHERE log_source = 'agent_session' AND instance_id = {sessionId:String}
             ORDER BY timestamp ASC`,
            { sessionId }
        )
    }

    /**
     * Poll `logsForSession` until at least one row matches `predicate`, or
     * the timeout elapses. Returns the matching set on success, throws on
     * timeout with the rows seen so far (helpful for diagnosing flakes).
     *
     * Kafka → CH eventual consistency is typically <500ms locally but can
     * spike; default budget is 10s with a 250ms poll interval.
     */
    async waitForLogs(
        sessionId: string,
        predicate: (rows: LogEntryRow[]) => boolean,
        opts: { timeoutMs?: number; intervalMs?: number } = {}
    ): Promise<LogEntryRow[]> {
        const timeout = opts.timeoutMs ?? 10_000
        const interval = opts.intervalMs ?? 250
        const start = Date.now()
        let lastSeen: LogEntryRow[] = []
        while (Date.now() - start < timeout) {
            lastSeen = await this.logsForSession(sessionId)
            if (predicate(lastSeen)) {
                return lastSeen
            }
            await new Promise((res) => setTimeout(res, interval))
        }
        throw new Error(
            `waitForLogs(${sessionId}) timed out after ${timeout}ms — last seen ${lastSeen.length} rows: ` +
                JSON.stringify(lastSeen.map((r) => ({ level: r.level, message: r.message })).slice(0, 5))
        )
    }

    private headers(): Record<string, string> {
        return {
            'x-clickhouse-user': this.auth.user,
            'x-clickhouse-key': this.auth.password,
        }
    }
}
