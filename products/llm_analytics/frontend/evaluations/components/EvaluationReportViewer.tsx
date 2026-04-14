import { useMemo, useState } from 'react'

import { LemonBadge, LemonButton, LemonCollapse, LemonDivider } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type {
    EvaluationReportMetrics,
    EvaluationReportRun,
    EvaluationReportRunContent,
    EvaluationReportSection,
} from '../types'

// Match any UUID in the content — surrounding punctuation (backticks, angle brackets, etc.)
// is stripped so we don't depend on how the LLM formats references.
const UUID_REGEX = /[`<]*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[`>]*/g

// Rewrite `<uuid>` backtick tokens into markdown links pointing to the correct
// trace URL. Uses the citations list to map generation_id → trace_id so the link
// opens the right trace with the generation highlighted.
function linkifyUuids(content: string, citationMap: Record<string, string>): string {
    return content.replace(UUID_REGEX, (_match, generationId: string) => {
        const traceId = citationMap[generationId]
        const url = traceId
            ? urls.llmAnalyticsTrace(traceId, { event: generationId })
            : urls.llmAnalyticsTrace(generationId)
        return `[\`${generationId.slice(0, 8)}...\`](${url})`
    })
}

// Strip a leading markdown heading line if it matches the section title.
// The agent sometimes prefixes each section's content with its own heading,
// which duplicates the heading the renderer emits separately.
function stripRedundantLeadingHeading(content: string, sectionTitle: string): string {
    const match = content.match(/^\s*(#{1,6})\s+(.+?)\s*(?:\r?\n|$)/)
    if (!match) {
        return content
    }
    const headingText = match[2].trim().toLowerCase()
    if (headingText.startsWith(sectionTitle.toLowerCase())) {
        return content.slice(match[0].length).replace(/^\s+/, '')
    }
    return content
}

function ReportSectionContent({
    section,
    citationMap,
}: {
    section: EvaluationReportSection
    citationMap: Record<string, string>
}): JSX.Element {
    const markdown = linkifyUuids(stripRedundantLeadingHeading(section.content, section.title), citationMap)
    return (
        <LemonMarkdown lowKeyHeadings className="text-sm">
            {markdown}
        </LemonMarkdown>
    )
}

function formatPassRate(rate: number | null | undefined): string {
    if (rate == null) {
        return '—'
    }
    return `${rate.toFixed(2)}%`
}

function MetricsCard({ metrics }: { metrics: EvaluationReportMetrics }): JSX.Element {
    // Period-over-period delta (if we have a previous pass rate to compare)
    let deltaEl: JSX.Element | null = null
    if (metrics.previous_pass_rate != null) {
        const diff = metrics.pass_rate - metrics.previous_pass_rate
        const arrow = diff > 0 ? '▲' : diff < 0 ? '▼' : '—'
        const color = diff > 0 ? 'text-success' : diff < 0 ? 'text-danger' : 'text-muted'
        deltaEl = (
            <span className={`text-xs ml-1 ${color}`}>
                {arrow} {Math.abs(diff).toFixed(2)}pp vs previous
            </span>
        )
    }

    return (
        <div className="bg-bg-light border rounded p-3 mb-3">
            <div className="flex items-center gap-6 flex-wrap text-sm">
                <div>
                    <div className="text-muted text-xs">Pass rate</div>
                    <div className="font-semibold">
                        {formatPassRate(metrics.pass_rate)}
                        {deltaEl}
                    </div>
                </div>
                <div>
                    <div className="text-muted text-xs">Total runs</div>
                    <div className="font-semibold">{metrics.total_runs}</div>
                </div>
                <div>
                    <div className="text-muted text-xs">Pass</div>
                    <div className="font-semibold text-success">{metrics.pass_count}</div>
                </div>
                <div>
                    <div className="text-muted text-xs">Fail</div>
                    <div className="font-semibold text-danger">{metrics.fail_count}</div>
                </div>
                <div>
                    <div className="text-muted text-xs">N/A</div>
                    <div className="font-semibold">{metrics.na_count}</div>
                </div>
                {metrics.previous_total_runs != null && (
                    <div>
                        <div className="text-muted text-xs">Previous runs</div>
                        <div className="font-semibold text-muted">{metrics.previous_total_runs}</div>
                    </div>
                )}
            </div>
        </div>
    )
}

function DeliveryStatusBadge({ status }: { status: string }): JSX.Element {
    const statusMap: Record<string, { label: string; status: 'success' | 'warning' | 'danger' | 'muted' }> = {
        delivered: { label: 'Delivered', status: 'success' },
        pending: { label: 'Pending', status: 'muted' },
        partial_failure: { label: 'Partial failure', status: 'warning' },
        failed: { label: 'Failed', status: 'danger' },
    }
    const info = statusMap[status] || { label: status, status: 'muted' as const }
    return <LemonBadge content={info.label} status={info.status} />
}

export function EvaluationReportViewer({
    reportRun,
    onClose,
    compact = false,
}: {
    reportRun: EvaluationReportRun
    onClose?: () => void
    /** When true, hides the header/close row — useful when the parent already provides framing (e.g. an expanded table row). */
    compact?: boolean
}): JSX.Element {
    const content = reportRun.content as EvaluationReportRunContent
    const sections = content.sections ?? []
    const metrics = content.metrics

    // Build generation_id → trace_id lookup from citations for correct trace URLs
    const citationMap = useMemo(() => {
        const map: Record<string, string> = {}
        for (const c of content.citations ?? []) {
            if (c.generation_id && c.trace_id) {
                map[c.generation_id] = c.trace_id
            }
        }
        return map
    }, [content.citations])

    // Default to executive summary (first section) expanded. Memoized so Expand/Collapse all
    // buttons can set the list deterministically.
    const sectionKeys = useMemo(() => sections.map((_, i) => i.toString()), [sections])
    const [expandedKeys, setExpandedKeys] = useState<string[]>(sections.length > 0 ? ['0'] : [])

    const allExpanded = expandedKeys.length === sectionKeys.length && sectionKeys.length > 0
    const allCollapsed = expandedKeys.length === 0

    return (
        <div>
            {!compact && (
                <>
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <h2 className="font-bold text-base mb-0">{content.title || 'Report'}</h2>
                            <DeliveryStatusBadge status={reportRun.delivery_status} />
                        </div>
                        {onClose && (
                            <LemonButton size="small" onClick={onClose}>
                                Close
                            </LemonButton>
                        )}
                    </div>
                    <div className="text-xs text-muted mb-3">
                        Period: {new Date(reportRun.period_start).toLocaleString()} –{' '}
                        {new Date(reportRun.period_end).toLocaleString()}
                    </div>

                    <LemonDivider className="my-3" />
                </>
            )}

            {compact && (
                <div className="flex items-center justify-between mb-2">
                    {content.title ? <h3 className="font-semibold text-sm mb-0">{content.title}</h3> : <div />}
                    {sections.length > 0 && (
                        <div className="flex gap-2">
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys(sectionKeys)}
                                disabledReason={allExpanded ? 'All sections already expanded' : undefined}
                            >
                                Expand all
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys([])}
                                disabledReason={allCollapsed ? 'All sections already collapsed' : undefined}
                            >
                                Collapse all
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}

            {metrics && <MetricsCard metrics={metrics} />}

            {sections.length > 0 && (
                <>
                    {!compact && (
                        <div className="flex justify-end gap-2 mb-2">
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys(sectionKeys)}
                                disabledReason={allExpanded ? 'All sections already expanded' : undefined}
                            >
                                Expand all
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setExpandedKeys([])}
                                disabledReason={allCollapsed ? 'All sections already collapsed' : undefined}
                            >
                                Collapse all
                            </LemonButton>
                        </div>
                    )}

                    <LemonCollapse
                        multiple
                        size="small"
                        activeKeys={expandedKeys}
                        onChange={(keys) => setExpandedKeys(keys as string[])}
                        panels={sections.map((section, idx) => ({
                            key: idx.toString(),
                            header: section.title,
                            content: <ReportSectionContent section={section} citationMap={citationMap} />,
                        }))}
                    />
                </>
            )}

            {reportRun.delivery_errors.length > 0 && (
                <div className="mt-4 p-2 bg-danger-highlight rounded">
                    <h4 className="font-semibold text-sm text-danger">Delivery errors</h4>
                    <ul className="text-xs">
                        {reportRun.delivery_errors.map((err, i) => (
                            <li key={i}>{err}</li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}
