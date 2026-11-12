import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { escapeHogQLString, hogql } from 'lib/utils/hogql'

/** How many people the list shows. The counts cover the whole run. */
export const NOT_SENT_ROW_LIMIT = 100

/**
 * Why a person in a run got no message. A paused or skipped email does not fail the run: the run
 * succeeds with an error in its log, so `skipped` is a succeeded run that logged an error.
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

/** One row per person in the run who got no message: a failed or canceled run, or a run that logged an error. */
function notSentInvocations(flowId: string, runId: string, runCreatedAt: string): ReturnType<typeof hogql.raw> {
    const flow = escapeHogQLString(flowId)
    // A run can be older than a day, so the window opens a day before it started.
    const from = escapeHogQLString(dayjs.utc(runCreatedAt).subtract(1, 'day').format('YYYY-MM-DD HH:mm:ss'))
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
          AND function_id = ${flow}
          AND parent_run_id = ${escapeHogQLString(runId)}
          AND scheduled_at >= toDateTime(${from})
        GROUP BY invocation_id
        HAVING argMax(is_deleted, version) = 0
           AND (
               status IN ('failed', 'canceled')
               OR (
                   status = 'succeeded'
                   AND invocation_id IN (
                       SELECT DISTINCT instance_id FROM log_entries
                       WHERE log_source = 'hog_flow' AND log_source_id = ${flow} AND lower(level) = 'error'
                   )
               )
           )
    `)
}

export async function loadBroadcastNotSent(
    flowId: string,
    runId: string,
    runCreatedAt: string
): Promise<BroadcastNotSent> {
    const invocations = notSentInvocations(flowId, runId, runCreatedAt)
    const tags = { scene: 'Broadcast', productKey: 'workflows' }
    const [rowsResponse, countsResponse] = await Promise.all([
        api.queryHogQL(
            hogql`SELECT invocation_id, status, error_message, distinct_id, person_id FROM (${invocations}) ORDER BY latest_scheduled_at DESC LIMIT ${NOT_SENT_ROW_LIMIT}`,
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

    // A skip, and some failures, put the reason only in the run's log, so the latest error line stands in.
    const withoutReason = rows.filter((row) => !row.reason).map((row) => escapeHogQLString(row.invocationId))
    if (withoutReason.length) {
        const logs = await api.queryHogQL(
            hogql`
                SELECT instance_id, argMax(message, timestamp)
                FROM log_entries
                WHERE log_source = 'hog_flow'
                  AND log_source_id = ${flowId}
                  AND lower(level) = 'error'
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
