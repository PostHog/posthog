import { LemonBanner, Link } from '@posthog/lemon-ui'

import { NewNotificationDialog } from 'scenes/hog-functions/list/NewNotificationDialog'
import { urls } from 'scenes/urls'

import { INSTANT_ALERT_USE_CASES, useInstantAlertRows } from './instantAlertRows'
import { AI_REPORT_LIST_LIMIT } from './mcpRecurringReportsLogic'
import { NotificationTypesTable } from './NotificationTypesTable'
import { useRecurringReportRows } from './recurringReportRows'

export function MCPAnalyticsNotifications(): JSX.Element {
    const alerts = useInstantAlertRows()
    const reports = useRecurringReportRows()
    const rows = [...(alerts.failed ? [] : alerts.rows), ...(reports.failed ? [] : reports.rows)]

    return (
        <div className="@container flex flex-col gap-3" data-attr="mcp-analytics-notifications">
            {alerts.failed && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: alerts.reload }}
                    data-attr="mcp-analytics-notifications-load-error"
                >
                    We couldn't load your MCP alerts. Please try again in a moment.
                </LemonBanner>
            )}
            {reports.failed && (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: reports.reload }}
                    data-attr="mcp-analytics-recurring-reports-load-error"
                >
                    We couldn't load your MCP reports. Please try again in a moment.
                </LemonBanner>
            )}

            {rows.length > 0 && <NotificationTypesTable rows={rows} />}

            {/* Say so rather than quietly dropping the tail — an invisible report is the bug this
                whole section exists to fix. */}
            {reports.truncated && (
                <p className="m-0 text-xs text-muted">
                    Showing the first {AI_REPORT_LIST_LIMIT} reports.{' '}
                    <Link to={urls.subscriptions()}>See all subscriptions</Link> for the rest.
                </p>
            )}

            {INSTANT_ALERT_USE_CASES.map((config) => (
                <NewNotificationDialog
                    key={config.subTemplateId}
                    subTemplateId={config.subTemplateId}
                    onCreated={alerts.reload}
                    title={config.dialogTitle}
                />
            ))}
        </div>
    )
}
