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

/** Whether a delivery row has any AI-generated detail to expand: an AI summary, the generating prompt,
 * the delivered report, or per-query diagnostics. Single source of truth for the table's `rowExpandable`
 * and `ExpandedDeliveryRow`'s early return, so the two can't disagree on which rows are expandable. */
export function deliveryRowHasExpandableContent(row: SubscriptionDeliveryApi): boolean {
    return (
        Boolean(row.change_summary) ||
        Boolean(row.ai_report) ||
        Boolean(row.ai_report_prompt) ||
        (row.ai_report_diagnostics ?? []).length > 0
    )
}

/**
 * Per-query accordion: one compact header per generated query (status + description); expand a query for its
 * SQL. Failed queries are open by default so a degraded report stays loud and debuggable.
 */
export function GeneratedQueries({ diagnostics }: { diagnostics: readonly AIReportQueryDiagnosticApi[] }): JSX.Element {
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

/** Expanded detail for a delivery row: the AI summary, the prompt at generation time, the delivered report,
 * and the per-query accordion. Returns null when there's nothing AI-generated to show. */
export function ExpandedDeliveryRow({ row }: { row: SubscriptionDeliveryApi }): JSX.Element | null {
    const diagnostics = row.ai_report_diagnostics ?? []
    const report = row.ai_report
    const prompt = row.ai_report_prompt
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
