import { LemonBadge, LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
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

function renderContentWithLinks(content: string): JSX.Element {
    const parts: (string | JSX.Element)[] = []
    let lastIndex = 0
    let match

    const regex = new RegExp(UUID_REGEX.source, 'g')
    while ((match = regex.exec(content)) !== null) {
        if (match.index > lastIndex) {
            parts.push(content.slice(lastIndex, match.index))
        }
        const genId = match[1]
        parts.push(
            <Link key={match.index} to={urls.llmAnalyticsTrace(genId)}>
                <code>{genId.slice(0, 8)}...</code>
            </Link>
        )
        lastIndex = match.index + match[0].length
    }
    if (lastIndex < content.length) {
        parts.push(content.slice(lastIndex))
    }

    return <span style={{ whiteSpace: 'pre-wrap' }}>{parts}</span>
}

function ReportSectionView({
    sectionKey,
    section,
}: {
    sectionKey: string
    section: EvaluationReportSection
}): JSX.Element {
    return (
        <div className="mb-4">
            <h3 className="font-semibold text-sm mb-1">{SECTION_TITLES[sectionKey] || sectionKey}</h3>
            <div className="text-sm text-default">{renderContentWithLinks(section.content)}</div>
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
}: {
    reportRun: EvaluationReportRun
    onClose?: () => void
}): JSX.Element {
    const content = reportRun.content as EvaluationReportRunContent

    return (
        <div>
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

            {SECTION_ORDER.map((key) => {
                const section = content[key as keyof EvaluationReportRunContent]
                if (!section) {
                    return null
                }
                return <ReportSectionView key={key} sectionKey={key} section={section} />
            })}

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
