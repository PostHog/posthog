import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCalendar, IconOpenSidebar, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { ConfirmDeleteButton } from 'lib/components/ConfirmDeleteButton'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { AI_REPORT_LIST_LIMIT, mcpRecurringReportsLogic } from './mcpRecurringReportsLogic'
import { MCP_RECURRING_REPORTS, MCPRecurringReport, urlForRecurringReport } from './recurringReportDefinitions'

function SavedReportRow({ report }: { report: SubscriptionApi }): JSX.Element {
    const { pendingToggleIds } = useValues(mcpRecurringReportsLogic)
    const { toggleReportEnabled, deleteReport } = useActions(mcpRecurringReportsLogic)

    return (
        <div className="flex items-center gap-2 rounded border p-2">
            <div className="min-w-0 flex-1">
                <Link to={urls.subscription(report.id)} className="truncate font-medium">
                    {report.title || 'Untitled report'}
                </Link>
                <div className="text-xs text-muted">
                    {report.summary}
                    {report.next_delivery_date && report.enabled ? (
                        <>
                            {' · next '}
                            <TZLabel time={report.next_delivery_date} />
                        </>
                    ) : null}
                </div>
            </div>
            <LemonSwitch
                checked={!!report.enabled}
                onChange={() => toggleReportEnabled(report.id, !report.enabled)}
                loading={!!pendingToggleIds[report.id]}
                aria-label={`Enable ${report.title || 'report'}`}
            />
            <ConfirmDeleteButton
                onDelete={() => deleteReport(report)}
                disabledReason={
                    pendingToggleIds[report.id] ? 'Waiting for the enable/disable update to finish…' : undefined
                }
                data-attr="mcp-analytics-recurring-report-delete"
            />
        </div>
    )
}

function ReportCard({
    report,
    enabled,
    savedReports,
}: {
    report: MCPRecurringReport
    enabled: boolean
    savedReports: SubscriptionApi[]
}): JSX.Element {
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
                        type={savedReports.length > 0 ? 'secondary' : 'primary'}
                        size="xsmall"
                        icon={savedReports.length > 0 ? <IconPlus /> : <IconCalendar />}
                        to={urlForRecurringReport(report)}
                        data-attr={`mcp-analytics-recurring-report-${report.key}`}
                    >
                        {savedReports.length > 0 ? 'Add' : 'Set up'}
                    </LemonButton>
                )}
            </div>

            {/* The report itself is written by an LLM each run, so there's nothing faithful to preview.
                Showing the question it asks is the honest version — and it's editable before saving. */}
            <div className="rounded border bg-surface-primary p-2">
                <div className="text-xs font-medium text-muted">What it asks</div>
                <p className="m-0 mt-0.5 text-xs">{report.prompt}</p>
            </div>

            {savedReports.length > 0 && (
                <div className="flex flex-col gap-1">
                    {savedReports.map((saved) => (
                        <SavedReportRow key={saved.id} report={saved} />
                    ))}
                </div>
            )}
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
    const { reports, reportsLoaded, reportsFailed, reportsTruncated } = useValues(mcpRecurringReportsLogic)
    const { loadReports } = useActions(mcpRecurringReportsLogic)

    // Loaded even without the feature flag: a project can hold reports created before the flag was
    // turned off, and hiding them would repeat the problem this list exists to fix.
    useEffect(() => {
        loadReports()
    }, [loadReports])

    // A saved report is tied back to the card that offers it by title, which is what the card's
    // deep-link sets. Renaming one moves it to "Other MCP reports" rather than losing it.
    const savedByTitle = (title: string): SubscriptionApi[] => reports.filter((saved) => saved.title === title)
    const templateTitles = new Set(MCP_RECURRING_REPORTS.map((report) => report.title))
    const otherReports = reports.filter((saved) => !saved.title || !templateTitles.has(saved.title))

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

            {reportsFailed && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadReports() }}
                    data-attr="mcp-analytics-recurring-reports-load-error"
                >
                    We couldn't load your MCP reports. Please try again in a moment.
                </LemonBanner>
            )}

            {/* Say so rather than quietly dropping the tail — an invisible report is the bug this
                whole section exists to fix. */}
            {reportsTruncated && (
                <p className="m-0 text-xs text-muted">
                    Showing the first {AI_REPORT_LIST_LIMIT} reports.{' '}
                    <Link to={urls.subscriptions()}>See all subscriptions</Link> for the rest.
                </p>
            )}

            <div className="grid gap-2 md:grid-cols-2">
                {MCP_RECURRING_REPORTS.map((report) => (
                    <ReportCard
                        key={report.key}
                        report={report}
                        enabled={aiSubscriptionsEnabled}
                        savedReports={reportsLoaded ? savedByTitle(report.title) : []}
                    />
                ))}
            </div>

            {!reportsLoaded && !reportsFailed && <LemonSkeleton className="h-8 w-full" />}

            {/* Anything MCP-related the cards don't account for still needs a home, so it can't be
                silently dropped from the list. */}
            {otherReports.length > 0 && (
                <LemonCard hoverEffect={false} className="flex flex-col gap-1 p-3">
                    <h3 className="m-0 text-sm font-semibold">Other MCP reports</h3>
                    {otherReports.map((saved) => (
                        <SavedReportRow key={saved.id} report={saved} />
                    ))}
                </LemonCard>
            )}
        </section>
    )
}
