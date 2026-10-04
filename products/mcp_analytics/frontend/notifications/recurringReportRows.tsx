import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCalendar, IconPlus } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { mcpRecurringReportsLogic } from './mcpRecurringReportsLogic'
import { countSaved, NotificationTypeRow } from './NotificationTypesTable'
import { MCP_RECURRING_REPORTS, MCPRecurringReport, urlForRecurringReport } from './recurringReportDefinitions'
import { RecurringReportDetails } from './RecurringReportDetails'
import { SavedNotificationRow } from './SavedNotificationRow'

function SavedReportRow({ report }: { report: SubscriptionApi }): JSX.Element {
    const { pendingToggleIds } = useValues(mcpRecurringReportsLogic)
    const { toggleReportEnabled, deleteReport } = useActions(mcpRecurringReportsLogic)

    return (
        <SavedNotificationRow
            name={report.title || 'Untitled report'}
            to={urls.subscription(report.id)}
            summary={
                <>
                    {report.summary}
                    {report.next_delivery_date && report.enabled ? (
                        <>
                            {' · next '}
                            <TZLabel time={report.next_delivery_date} />
                        </>
                    ) : null}
                </>
            }
            enabled={!!report.enabled}
            onToggle={(enabled) => toggleReportEnabled(report.id, enabled)}
            toggleLoading={!!pendingToggleIds[report.id]}
            onDelete={() => deleteReport(report)}
            deleteDisabledReason={
                pendingToggleIds[report.id] ? 'Waiting for the enable/disable update to finish…' : undefined
            }
            deleteDataAttr="mcp-analytics-recurring-report-delete"
        />
    )
}

// `mayExist` covers a cut list too: a match may sit past the page limit, so the row must not push
// a primary "Set up" that creates a duplicate.
function reportAction(report: MCPRecurringReport, mayExist: boolean): JSX.Element {
    return (
        <LemonButton
            type={mayExist ? 'secondary' : 'primary'}
            size="small"
            icon={mayExist ? <IconPlus /> : undefined}
            to={urlForRecurringReport(report)}
            data-attr={`mcp-analytics-recurring-report-${report.key}`}
        >
            {mayExist ? 'Add' : 'Set up'}
        </LemonButton>
    )
}

export interface RecurringReportRows {
    rows: NotificationTypeRow[]
    loaded: boolean
    failed: boolean
    truncated: boolean
    reload: () => void
}

/**
 * Recurring AI reports for the two questions that suit a digest better than a per-event ping: what
 * agents keep asking for, and how the tools are holding up. Both are summaries over a window, so
 * they stay useful on a quiet server and can't flood a channel the way a per-event alert can.
 */
export function useRecurringReportRows(): RecurringReportRows {
    const { reportsByTemplateTitle, otherReports, reportsLoaded, reportsFailed, reportsTruncated } =
        useValues(mcpRecurringReportsLogic)
    const { loadReports } = useActions(mcpRecurringReportsLogic)
    useEffect(() => {
        loadReports()
    }, [loadReports])

    const rows: NotificationTypeRow[] = MCP_RECURRING_REPORTS.map((report) => {
        const saved = reportsLoaded ? (reportsByTemplateTitle[report.title] ?? []) : []
        return {
            key: `report-${report.key}`,
            icon: <IconCalendar />,
            headline: report.headline,
            lead: report.lead,
            tag: (
                <LemonTag type="completion" size="small">
                    Beta
                </LemonTag>
            ),
            cadence: report.frequency,
            saved: reportsLoaded ? countSaved(saved, reportsTruncated) : undefined,
            action: reportAction(report, saved.length > 0 || reportsTruncated),
            preview: <RecurringReportDetails covers={report.covers} prompt={report.prompt} />,
            savedRows: saved.map((report) => <SavedReportRow key={report.id} report={report} />),
        }
    })

    if (otherReports.length > 0) {
        rows.push({
            key: 'report-other',
            icon: <IconCalendar />,
            headline: 'Other MCP reports',
            lead: 'Reports that mention MCP but do not match a template above.',
            saved: countSaved(otherReports, reportsTruncated),
            savedRows: otherReports.map((report) => <SavedReportRow key={report.id} report={report} />),
        })
    }

    return { rows, loaded: reportsLoaded, failed: reportsFailed, truncated: reportsTruncated, reload: loadReports }
}
