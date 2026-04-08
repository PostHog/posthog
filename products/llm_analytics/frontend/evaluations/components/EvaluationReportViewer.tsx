import { useMemo, useState } from 'react'

import { LemonBadge, LemonButton, LemonCollapse, LemonDivider } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type { EvaluationReportRun, EvaluationReportRunContent, EvaluationReportSection } from '../types'

const SECTION_TITLES: Record<string, string> = {
    executive_summary: 'Executive summary',
    statistics: 'Statistics',
    trend_analysis: 'Trend analysis',
    failure_patterns: 'Failure patterns',
    pass_patterns: 'Pass patterns',
    notable_changes: 'Notable changes',
    recommendations: 'Recommendations',
    risk_assessment: 'Risk assessment',
}

const SECTION_ORDER = [
    'executive_summary',
    'statistics',
    'trend_analysis',
    'failure_patterns',
    'pass_patterns',
    'notable_changes',
    'recommendations',
    'risk_assessment',
]

const UUID_REGEX = /`([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`/g

// Rewrite `<uuid>` backtick tokens into markdown links so LemonMarkdown renders
// them as clickable trace links. The generated URL matches the current behaviour
// of the old renderer — the citation-URL bug is tracked in beads-tracking-17d.
function linkifyUuids(content: string): string {
    return content.replace(UUID_REGEX, (_match, uuid: string) => {
        return `[\`${uuid.slice(0, 8)}...\`](${urls.llmAnalyticsTrace(uuid)})`
    })
}

// The agent typically emits each section starting with its own `#`/`##` heading
// matching (or closely matching) the section title. The viewer already renders
// a `<h3>` for the canonical title, so that heading is redundant. Strip any
// leading heading line whose text starts with the canonical section title
// (case-insensitive), to keep the rendering clean without touching the stored
// report content.
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

function ReportSectionContent({ section, title }: { section: EvaluationReportSection; title: string }): JSX.Element {
    const markdown = linkifyUuids(stripRedundantLeadingHeading(section.content, title))
    return (
        <LemonMarkdown lowKeyHeadings className="text-sm">
            {markdown}
        </LemonMarkdown>
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

    // Build the list of sections that actually have content, in canonical order.
    // Memoized so identity is stable and expand/collapse all buttons don't thrash.
    const availableSectionKeys = useMemo(
        () =>
            SECTION_ORDER.filter(
                (key) => content[key as keyof EvaluationReportRunContent] != null
            ) as (keyof EvaluationReportRunContent)[],
        [content]
    )

    // Default to just the executive summary expanded — that's the TL;DR and keeps
    // the list scannable. Users can Expand all for full view.
    const [expandedKeys, setExpandedKeys] = useState<string[]>(
        availableSectionKeys.includes('executive_summary') ? ['executive_summary'] : []
    )

    const allExpanded = expandedKeys.length === availableSectionKeys.length
    const allCollapsed = expandedKeys.length === 0

    return (
        <div>
            {!compact && (
                <>
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <h2 className="font-bold text-base mb-0">Report</h2>
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

            <div className="flex justify-end gap-2 mb-2">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => setExpandedKeys(availableSectionKeys as string[])}
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

            <LemonCollapse
                multiple
                size="small"
                activeKeys={expandedKeys}
                onChange={(keys) => setExpandedKeys(keys as string[])}
                panels={availableSectionKeys.map((key) => {
                    const section = content[key]!
                    const title = SECTION_TITLES[key] || key
                    return {
                        key,
                        header: title,
                        content: <ReportSectionContent section={section} title={title} />,
                    }
                })}
            />

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
