import { IconCalendar, IconOpenSidebar } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { MCP_RECURRING_REPORTS, MCPRecurringReport, urlForRecurringReport } from './recurringReportDefinitions'

function ReportCard({ report, enabled }: { report: MCPRecurringReport; enabled: boolean }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3">
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                        <h3 className="m-0 text-sm font-semibold">{report.headline}</h3>
                        <LemonTag type="muted" size="small">
                            {report.frequency === 'daily' ? 'Daily' : 'Weekly'}
                        </LemonTag>
                    </div>
                    <p className="m-0 text-xs text-muted">{report.lead}</p>
                </div>
                {enabled && (
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        icon={<IconCalendar />}
                        to={urlForRecurringReport(report)}
                        data-attr={`mcp-analytics-recurring-report-${report.key}`}
                    >
                        Set up
                    </LemonButton>
                )}
            </div>

            {/* The report itself is written by an LLM each run, so there's nothing faithful to preview.
                Showing the question it asks is the honest version — and it's editable before saving. */}
            <div className="rounded border bg-surface-primary p-2">
                <div className="text-xs font-medium text-muted">What it asks</div>
                <p className="m-0 mt-0.5 text-xs">{report.prompt}</p>
            </div>
        </LemonCard>
    )
}

/**
 * Recurring AI reports for the two questions that suit a digest better than a per-event ping: what
 * agents keep asking for, and how the tools are holding up. Both are summaries over a window, so
 * they stay useful on a quiet server and can't flood a channel the way a per-event alert can.
 */
export function MCPRecurringReports(): JSX.Element {
    const aiSubscriptionsEnabled = useFeatureFlag('SUBSCRIPTION_AI_PROMPT')

    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
                <h2 className="m-0 text-base font-semibold">Recurring reports</h2>
                <LemonTag type="completion">Beta</LemonTag>
            </div>
            <p className="m-0 text-sm text-muted">
                A written summary on a schedule, delivered to Slack or email. Best for the questions you want to think
                about regularly rather than react to.
            </p>

            {!aiSubscriptionsEnabled && (
                <p className="m-0 text-xs text-muted">
                    AI reports are in early access.{' '}
                    <Link to={urls.featurePreview(FEATURE_FLAGS.SUBSCRIPTION_AI_PROMPT)}>
                        Turn them on for your account <IconOpenSidebar />
                    </Link>{' '}
                    to set one up.
                </p>
            )}

            <div className="grid gap-2 md:grid-cols-2">
                {MCP_RECURRING_REPORTS.map((report) => (
                    <ReportCard key={report.key} report={report} enabled={aiSubscriptionsEnabled} />
                ))}
            </div>
        </section>
    )
}
