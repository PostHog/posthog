import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { escapeHogQLString, hogql } from 'lib/utils/hogql'

/** How many people the list shows. The counts cover the whole run. */
export const NOT_SENT_ROW_LIMIT = 100

/**
 * Why a person in a run got no message. A skipped email (paused, opted out, suppressed, no address)
 * does not fail the run: the run succeeds and only its log records the skip.
 */
export type NotSentKind = 'failed' | 'skipped' | 'canceled'

export interface NotSentRow {
    invocationId: string
    distinctId: string
    personId: string
    kind: NotSentKind
    reason: string
}

export type NotSentCounts = Record<NotSentKind, number>

export interface BroadcastNotSent {
    rows: NotSentRow[]
    counts: NotSentCounts
}

export function notSentKind(status: string): NotSentKind {
    return status === 'failed' || status === 'canceled' ? status : 'skipped'
}

export function notSentTotal(counts: NotSentCounts): number {
    return counts.failed + counts.skipped + counts.canceled
}

/**
 * Run log lines that mean a person got no message. The worker records a skip in the log only, at
 * any level (an opt-out or suppression logs info, a missing address warn, a paused send error), so
 * skips are matched on the wording the email step uses. Logs are keyed by the run, not the workflow.
 */
function notSentLogFilter(runId: string, from: string): string {
    return `log_source = 'hog_flow'
        AND log_source_id = ${escapeHogQLString(runId)}
        AND timestamp >= toDateTime(${from})
        AND (
            lower(level) = 'error'
            OR message ILIKE 'Skipping send%'
            OR message ILIKE '%skipping message delivery%'
        )`
}

/** A run can be older than a day, so the window opens a day before it started. */
function windowStart(runCreatedAt: string): string {
    return escapeHogQLString(dayjs.utc(runCreatedAt).subtract(1, 'day').format('YYYY-MM-DD HH:mm:ss'))
}

/** One row per person in the run who got no message: a failed or canceled run, or a run that logged a skip. */
function notSentInvocations(
    flowId: string,
    runId: string,
    runCreatedAt: string,
    search = ''
): ReturnType<typeof hogql.raw> {
    const from = windowStart(runCreatedAt)
    const logFilter = notSentLogFilter(runId, from)
    // ILIKE treats % and _ as wildcards, so they are escaped to match a search term literally.
    const like = escapeHogQLString(`%${search.replace(/[\\%_]/g, '\\$&')}%`)
    // A skipped person's reason is only in the run log, so the search reads the log too.
    const searchClause = search
        ? `AND (
               distinct_id ILIKE ${like}
               OR error_message ILIKE ${like}
               OR invocation_id IN (SELECT DISTINCT instance_id FROM log_entries WHERE ${logFilter} AND message ILIKE ${like})
           )`
        : ''
    return hogql.raw(`
        SELECT
            invocation_id,
            argMax(status, version) AS status,
            argMax(error_message, version) AS error_message,
            argMax(distinct_id, version) AS distinct_id,
            argMax(person_id, version) AS person_id,
            max(scheduled_at) AS latest_scheduled_at
        FROM posthog.hog_invocation_results
        WHERE function_kind = 'hog_flow'
          AND function_id = ${escapeHogQLString(flowId)}
          AND parent_run_id = ${escapeHogQLString(runId)}
          AND scheduled_at >= toDateTime(${from})
        GROUP BY invocation_id
        HAVING argMax(is_deleted, version) = 0
           AND (
               status IN ('failed', 'canceled')
               OR (status = 'succeeded' AND invocation_id IN (SELECT DISTINCT instance_id FROM log_entries WHERE ${logFilter}))
           )
           ${searchClause}
    `)
}

/** The counts always cover the whole run. `search` narrows only the listed people. */
export async function loadBroadcastNotSent(
    flowId: string,
    runId: string,
    runCreatedAt: string,
    search = ''
): Promise<BroadcastNotSent> {
    const invocations = notSentInvocations(flowId, runId, runCreatedAt)
    const listed = search ? notSentInvocations(flowId, runId, runCreatedAt, search) : invocations
    const tags = { scene: 'Broadcast', productKey: 'workflows' }
    const [rowsResponse, countsResponse] = await Promise.all([
        api.queryHogQL(
            hogql`SELECT invocation_id, status, error_message, distinct_id, person_id FROM (${listed}) ORDER BY latest_scheduled_at DESC LIMIT ${NOT_SENT_ROW_LIMIT}`,
            tags,
            { refresh: 'force_blocking' }
        ),
        api.queryHogQL(hogql`SELECT status, count() FROM (${invocations}) GROUP BY status`, tags, {
            refresh: 'force_blocking',
        }),
    ])

    const rows: NotSentRow[] = (rowsResponse.results ?? []).map((row: any[]) => ({
        invocationId: String(row[0]),
        kind: notSentKind(String(row[1])),
        reason: String(row[2] ?? ''),
        distinctId: String(row[3] ?? ''),
        personId: String(row[4] ?? ''),
    }))
    const counts: NotSentCounts = { failed: 0, skipped: 0, canceled: 0 }
    for (const [status, count] of countsResponse.results ?? []) {
        counts[notSentKind(String(status))] += Number(count)
    }

    // A skip, and some failures, put the reason only in the run's log, so the latest such line stands in.
    const withoutReason = rows.filter((row) => !row.reason).map((row) => escapeHogQLString(row.invocationId))
    if (withoutReason.length) {
        const logs = await api.queryHogQL(
            hogql`
                SELECT instance_id, argMax(message, timestamp)
                FROM log_entries
                WHERE ${hogql.raw(notSentLogFilter(runId, windowStart(runCreatedAt)))}
                  AND instance_id IN (${hogql.raw(withoutReason.join(', '))})
                GROUP BY instance_id
            `,
            tags,
            { refresh: 'force_blocking' }
        )
        const reasonById = new Map((logs.results ?? []).map((row: any[]) => [String(row[0]), String(row[1])]))
        for (const row of rows) {
            row.reason ||= reasonById.get(row.invocationId) ?? ''
        }
    }
    return { rows, counts }
}
