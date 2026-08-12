import { useMemo } from 'react'

import { LemonCollapse, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type {
    AIReportQueryDiagnosticApi,
    SubscriptionDeliveryApi,
} from 'products/subscriptions/frontend/generated/api.schemas'
import { SubscriptionDeliveryStatusEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

/** A completed AI delivery whose report couldn't compute some queries still shipped — but with missing
 * metrics — so it reads as "Partial", not a clean "Completed". Derived from the (query:viewer-gated)
 * diagnostics the viewer already has; a query-restricted caller (diagnostics scrubbed) sees "Completed". */
export function isPartialDelivery(row: Pick<SubscriptionDeliveryApi, 'status' | 'ai_report_diagnostics'>): boolean {
    if (row.status !== SubscriptionDeliveryStatusEnumApi.Completed) {
        return false
    }
    return (row.ai_report_diagnostics ?? []).some((d) => d.ok === false)
}

/** The "Partial" status tag for a completed delivery whose report couldn't compute some queries. Null when
 * the delivery isn't partial (or its diagnostics are scrubbed), so the caller falls back to the plain tag. */
export function partialDeliveryTag(row: SubscriptionDeliveryApi): JSX.Element | null {
    if (!isPartialDelivery(row)) {
        return null
    }
    const diagnostics = row.ai_report_diagnostics ?? []
    const failed = diagnostics.filter((d) => d.ok === false).length
    return (
        <Tooltip
            title={`${failed} of ${diagnostics.length} queries failed — those metrics are missing from the report.`}
        >
            <LemonTag type="warning" className="cursor-help">
                Partial
            </LemonTag>
        </Tooltip>
    )
}

/** Header label for a query outcome. A failed query shows its specific error type only when we can also
 * explain it (a message is present, i.e. a resolution/exposed HogQL error); a generic/internal exception
 * collapses to a plain "Failed" so a cryptic class name like "Exception" never leaks into the header. */
export function queryStatusLabel(
    d: Pick<AIReportQueryDiagnosticApi, 'ok' | 'error_type' | 'human_readable_error'>
): string {
    if (d.ok !== false) {
        return 'OK'
    }
    return d.human_readable_error && d.error_type ? d.error_type : 'Failed'
}

/** Failure reason shown in a failed query's expanded panel: the safe message when we have one, otherwise a
 * plain internal-error note (we deliberately don't surface internal exception text). Null for a succeeded query. */
export function queryFailureReason(d: Pick<AIReportQueryDiagnosticApi, 'ok' | 'human_readable_error'>): string | null {
    if (d.ok !== false) {
        return null
    }
    return d.human_readable_error || 'This query failed to run due to an internal error.'
}

function queryStatusTag(d: AIReportQueryDiagnosticApi): JSX.Element {
    return <LemonTag type={d.ok === false ? 'danger' : 'success'}>{queryStatusLabel(d)}</LemonTag>
}

function diagnosticsSummary(diagnostics: readonly AIReportQueryDiagnosticApi[]): string {
    const total = diagnostics.length
    const failed = diagnostics.filter((d) => d.ok === false).length
    const noun = total === 1 ? 'query' : 'queries'
    return failed === 0 ? `${total} ${noun} · all succeeded` : `${total} ${noun} · ${failed} failed`
}

const failedIndexes = (diagnostics: readonly AIReportQueryDiagnosticApi[]): number[] =>
    diagnostics.map((d, i) => (d.ok === false ? i : -1)).filter((i) => i >= 0)

/* ------------------------------------------------------------------ */
/* Per-recipient results                                              */
/* ------------------------------------------------------------------ */

type DeliveryRecipientStatus = 'success' | 'failed' | 'partial'

interface DeliveryRecipientResult {
    recipient: string
    status: DeliveryRecipientStatus
    error: { message?: string } | null
    /** Owner-safe failure reason from the backend; never the raw exception text in `error.message`. */
    human_readable_error: string | null
}

/** Narrow the API's untyped `recipient_results` JSON into a typed list. Anything that doesn't match the
 * expected shape is dropped rather than erroring, so a partially-formed payload still shows what it can. */
function parseRecipientResults(raw: SubscriptionDeliveryApi['recipient_results']): DeliveryRecipientResult[] {
    if (!Array.isArray(raw)) {
        return []
    }
    return raw
        .map((r): DeliveryRecipientResult | null => {
            if (typeof r !== 'object' || r === null) {
                return null
            }
            const recipient = typeof (r as any).recipient === 'string' ? (r as any).recipient : null
            const status = (r as any).status
            if (!recipient || (status !== 'success' && status !== 'failed' && status !== 'partial')) {
                return null
            }
            const error = typeof (r as any).error === 'object' && (r as any).error !== null ? (r as any).error : null
            const humanReadable =
                typeof (r as any).human_readable_error === 'string' ? (r as any).human_readable_error : null
            return { recipient, status, error, human_readable_error: humanReadable }
        })
        .filter((r): r is DeliveryRecipientResult => r !== null)
}

/** What to show for a failed recipient: the backend's safe human_readable_error when present, else a
 * generic note. We deliberately never surface the raw exception text in error.message. */
function recipientFailureReason(r: Pick<DeliveryRecipientResult, 'human_readable_error'>): string {
    return r.human_readable_error || 'Delivery to this destination failed due to an internal error.'
}

function recipientStatusTag(status: DeliveryRecipientStatus): JSX.Element {
    if (status === 'success') {
        return <LemonTag type="success">Success</LemonTag>
    }
    if (status === 'failed') {
        return <LemonTag type="danger">Failed</LemonTag>
    }
    return <LemonTag type="warning">Partial</LemonTag>
}

/** Summary line for a recipients list. Null when every row shares one status — a tag per row already says
 * that, so a count would be redundant. Only the mixed outcome spells out the split. */
function recipientResultsSummary(results: readonly DeliveryRecipientResult[]): string | null {
    const total = results.length
    const succeeded = results.filter((r) => r.status === 'success').length
    const partial = results.filter((r) => r.status === 'partial').length
    const failed = results.filter((r) => r.status === 'failed').length
    const distinctStatuses = [succeeded > 0, partial > 0, failed > 0].filter(Boolean).length
    if (distinctStatuses < 2) {
        return null
    }
    const noun = total === 1 ? 'recipient' : 'recipients'
    const parts: string[] = []
    if (succeeded > 0) {
        parts.push(`${succeeded} succeeded`)
    }
    if (partial > 0) {
        parts.push(`${partial} partial`)
    }
    if (failed > 0) {
        parts.push(`${failed} failed`)
    }
    return `${total} ${noun} · ${parts.join(' · ')}`
}

// Success first, then partial, then failed — so failures sink to the bottom where they're easy to act on.
const RECIPIENT_STATUS_ORDER: Record<DeliveryRecipientStatus, number> = { success: 0, partial: 1, failed: 2 }

function DeliveryRecipients({ results }: { results: readonly DeliveryRecipientResult[] }): JSX.Element {
    const sorted = useMemo(
        () => [...results].sort((a, b) => RECIPIENT_STATUS_ORDER[a.status] - RECIPIENT_STATUS_ORDER[b.status]),
        [results]
    )
    const summary = recipientResultsSummary(results)
    return (
        <div className="flex flex-col gap-2">
            {summary ? <div className="text-secondary">{summary}</div> : null}
            <div className="flex flex-col divide-y rounded border bg-bg-light">
                {sorted.map((r, index) => (
                    // Index in the key: the abort path can legitimately record two results for one recipient
                    // (planner-rejection detail + disable reason), so recipient alone isn't unique.
                    <div key={`${r.recipient}-${index}`} className="flex flex-col gap-1 px-3 py-2">
                        <div className="flex items-center gap-2">
                            {recipientStatusTag(r.status)}
                            <span className="font-medium break-all">{r.recipient}</span>
                        </div>
                        {r.status === 'failed' || r.status === 'partial' ? (
                            <div className={r.status === 'failed' ? 'text-danger text-xs' : 'text-warning text-xs'}>
                                {recipientFailureReason(r)}
                            </div>
                        ) : null}
                    </div>
                ))}
            </div>
        </div>
    )
}

/* ------------------------------------------------------------------ */
/* Per-insight items (dashboard / insight exports)                    */
/* ------------------------------------------------------------------ */

interface DeliveryInsightItem {
    key: string
    name: string
    /** True only when a query_error is present. Absence of query_error AND query_results means the item is a
     * pre-execution skeleton (a stuck/interrupted run) that never computed — rendered as pending, not success. */
    failed: boolean
    /** True when neither results nor an error were recorded, so the query never ran. */
    pending: boolean
    /** Owner-safe failure reason from the backend (never the raw exception text). */
    humanReadableError: string | null
}

/** Narrow the API's untyped `content_snapshot.insights[]` into a typed list. Each insight entry carries an
 * id/short_id/name plus an optional `query_error` marking that specific item's failure. */
function parseContentSnapshotInsights(raw: SubscriptionDeliveryApi['content_snapshot']): DeliveryInsightItem[] {
    if (typeof raw !== 'object' || raw === null) {
        return []
    }
    const insights = (raw as any).insights
    if (!Array.isArray(insights)) {
        return []
    }
    return insights
        .map((ins, index): DeliveryInsightItem | null => {
            if (typeof ins !== 'object' || ins === null) {
                return null
            }
            const name =
                typeof ins.name === 'string' && ins.name
                    ? ins.name
                    : typeof ins.short_id === 'string' && ins.short_id
                      ? ins.short_id
                      : `Insight ${index + 1}`
            const queryError = typeof ins.query_error === 'object' && ins.query_error !== null ? ins.query_error : null
            const hasResults = typeof ins.query_results === 'object' && ins.query_results !== null
            const humanReadableError =
                queryError && typeof queryError.human_readable_error === 'string'
                    ? queryError.human_readable_error
                    : null
            const key =
                ins.id != null
                    ? `id:${ins.id}`
                    : typeof ins.short_id === 'string'
                      ? `short:${ins.short_id}`
                      : `idx:${index}`
            return {
                key,
                name,
                failed: queryError !== null,
                pending: queryError === null && !hasResults,
                humanReadableError,
            }
        })
        .filter((i): i is DeliveryInsightItem => i !== null)
}

/** Summary line for a content list. Null when there's nothing to break down (no failures and no pending items —
 * the per-item tags already say "Computed"). Only surfaces when some item didn't cleanly compute. */
function insightItemsSummary(items: readonly DeliveryInsightItem[]): string | null {
    const total = items.length
    const failed = items.filter((i) => i.failed).length
    const pending = items.filter((i) => i.pending).length
    const computed = total - failed - pending
    if (failed === 0 && pending === 0) {
        return null
    }
    const noun = total === 1 ? 'item' : 'items'
    const parts: string[] = []
    if (computed > 0) {
        parts.push(`${computed} computed`)
    }
    if (pending > 0) {
        parts.push(`${pending} did not run`)
    }
    if (failed > 0) {
        parts.push(`${failed} failed to compute`)
    }
    return `${total} ${noun} · ${parts.join(' · ')}`
}

// Computed first, then pending, then failed — actionable failures sink to the bottom.
const INSIGHT_ITEM_ORDER = (item: DeliveryInsightItem): number => (item.failed ? 2 : item.pending ? 1 : 0)

function insightItemTag(item: DeliveryInsightItem): JSX.Element {
    if (item.failed) {
        return <LemonTag type="danger">Failed</LemonTag>
    }
    if (item.pending) {
        return <LemonTag type="default">Did not run</LemonTag>
    }
    return <LemonTag type="success">Computed</LemonTag>
}

function DeliveryInsightItems({ items }: { items: readonly DeliveryInsightItem[] }): JSX.Element {
    const sorted = useMemo(() => [...items].sort((a, b) => INSIGHT_ITEM_ORDER(a) - INSIGHT_ITEM_ORDER(b)), [items])
    const summary = insightItemsSummary(items)
    return (
        <div className="flex flex-col gap-2">
            {summary ? <div className="text-secondary">{summary}</div> : null}
            <div className="flex flex-col divide-y rounded border bg-bg-light">
                {sorted.map((item) => (
                    <div key={item.key} className="flex flex-col gap-1 px-3 py-2">
                        <div className="flex items-center gap-2">
                            {insightItemTag(item)}
                            <span className="font-medium break-all">{item.name}</span>
                        </div>
                        {item.failed ? (
                            <div className="text-danger text-xs">
                                {item.humanReadableError || 'This item failed to run due to an internal error.'}
                            </div>
                        ) : null}
                    </div>
                ))}
            </div>
        </div>
    )
}

/** Whether a delivery row has any detail to expand: AI-generated content (summary, prompt, report, per-query
 * diagnostics) or per-item delivery detail (recipients / exported insights). Single source of truth for the
 * table's `rowExpandable` and `ExpandedDeliveryRow`'s early return, so the two can't disagree on which rows
 * are expandable. */
export function deliveryRowHasExpandableContent(row: SubscriptionDeliveryApi): boolean {
    if (row.change_summary || row.ai_report || row.ai_report_prompt || (row.ai_report_diagnostics ?? []).length > 0) {
        return true
    }
    if (Array.isArray(row.recipient_results) && row.recipient_results.length > 0) {
        return true
    }
    // Skeleton-only snapshots (stuck runs where every insight is still pending) have nothing actionable
    // to show — don't offer an expand chevron for them. The full parse happens in ExpandedDeliveryRow.
    if (!row.content_snapshot || typeof row.content_snapshot !== 'object') {
        return false
    }
    const insights = (row.content_snapshot as { insights?: unknown }).insights
    if (!Array.isArray(insights)) {
        return false
    }
    return insights.some(
        (ins) => typeof ins === 'object' && ins !== null && ('query_results' in ins || 'query_error' in ins)
    )
}

/**
 * Per-query accordion: one compact header per generated query (status + description); expand a query for its
 * SQL. Failed queries are open by default so a degraded report stays loud and debuggable.
 */
function GeneratedQueries({ diagnostics }: { diagnostics: readonly AIReportQueryDiagnosticApi[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="text-secondary">{diagnosticsSummary(diagnostics)}</div>
            <LemonCollapse
                size="small"
                multiple
                defaultActiveKeys={failedIndexes(diagnostics)}
                panels={diagnostics.map((d, index) => ({
                    key: index,
                    header: (
                        <div className="flex items-center gap-2">
                            {queryStatusTag(d)}
                            <span>{d.description || 'Query'}</span>
                        </div>
                    ),
                    content: (
                        <div className="flex flex-col gap-2">
                            {d.ok === false ? (
                                <div className={d.human_readable_error ? 'text-danger' : 'text-secondary'}>
                                    {queryFailureReason(d)}
                                </div>
                            ) : null}
                            {d.hogql ? (
                                <CodeSnippet language={Language.SQL} compact>
                                    {d.hogql}
                                </CodeSnippet>
                            ) : (
                                <span className="text-secondary">No query captured.</span>
                            )}
                        </div>
                    ),
                }))}
            />
        </div>
    )
}

/** Expanded detail for a delivery row: AI summary, prompt at generation time, delivered report, per-query
 * accordion, plus per-recipient and per-insight delivery outcomes. Returns null when there's nothing to show. */
export function ExpandedDeliveryRow({ row }: { row: SubscriptionDeliveryApi }): JSX.Element | null {
    const diagnostics = row.ai_report_diagnostics ?? []
    const report = row.ai_report
    const prompt = row.ai_report_prompt
    // Memoized: payloads can be large for dashboard exports and this row re-renders with the table.
    const recipients = useMemo(() => parseRecipientResults(row.recipient_results), [row.recipient_results])
    const insights = useMemo(() => parseContentSnapshotInsights(row.content_snapshot), [row.content_snapshot])
    if (!deliveryRowHasExpandableContent(row)) {
        return null
    }
    return (
        <div className="px-4 py-3 text-sm flex flex-col gap-4">
            {row.change_summary ? (
                <div className="whitespace-pre-wrap">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1">AI summary</div>
                    {row.change_summary}
                </div>
            ) : null}
            {prompt ? (
                <div className="whitespace-pre-wrap">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1">
                        Prompt at time of generation
                    </div>
                    {prompt}
                </div>
            ) : null}
            {report ? (
                <div className="flex flex-col gap-1">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary">Delivered report</div>
                    <div className="max-h-96 overflow-auto rounded border bg-bg-light p-3">
                        {/* LLM-generated content: disableImages so an image URL in the report can't auto-fire a
                            request (tracking pixel / IP leak / internal-address probe) when a teammate opens this. */}
                        <LemonMarkdown disableImages>{report}</LemonMarkdown>
                    </div>
                </div>
            ) : null}
            {recipients.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary">Delivery</div>
                    <DeliveryRecipients results={recipients} />
                </div>
            ) : null}
            {insights.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary">Content</div>
                    <DeliveryInsightItems items={insights} />
                </div>
            ) : null}
            {diagnostics.length > 0 ? (
                <div className="flex flex-col gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-secondary">
                        Generated queries
                    </div>
                    <GeneratedQueries diagnostics={diagnostics} />
                </div>
            ) : null}
        </div>
    )
}
