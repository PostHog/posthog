import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTarget } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'
import {
    buildReportCheckRows,
    latestCheckExplanations,
    reportChecksMeta,
    splitReportCheckRows,
} from './reportCheckPresentation'
import { ReportCheckRow } from './ReportCheckRow'

/**
 * What is still watching this report, and what the checks that already ran decided. A check is the
 * one forward-looking row a report carries: an expectation plus the time to test it. Until it
 * produces a verdict nothing else on the page mentions it, so a reader cannot otherwise tell that a
 * check is scheduled, waiting for the report to resolve, or expired without ever running.
 *
 * Reads the report's checks endpoint and the artefacts the detail logic already loads, which is
 * where a finished check's explanation lives. Hidden entirely when the report has no checks, so the
 * rail does not grow an empty section on the reports that carry none.
 */
export function ReportChecksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportChecks, reportChecksLoading, reportArtefacts, cancellingCheckIds } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const { cancelReportCheck } = useActions(inboxReportDetailLogic({ reportId: report.id, report }))
    const [showRetired, setShowRetired] = useState(false)

    if (reportChecksLoading && !reportChecks) {
        return (
            <DetailSection icon={<IconTarget />} title="Follow-up checks" collapsible>
                <LemonSkeleton className="h-12 w-full" />
            </DetailSection>
        )
    }

    if (!reportChecks || reportChecks.length === 0) {
        return null
    }

    const rows = buildReportCheckRows(reportChecks, latestCheckExplanations(reportArtefacts ?? []))
    const { visible, hidden } = splitReportCheckRows(rows)

    return (
        <DetailSection
            icon={<IconTarget />}
            title="Follow-up checks"
            collapsible
            meta={<span className="text-xs text-tertiary tabular-nums">{reportChecksMeta(reportChecks)}</span>}
        >
            <div className="flex flex-col gap-1.5">
                {(showRetired ? rows : visible).map((row) => (
                    <ReportCheckRow
                        key={row.check.id}
                        row={row}
                        cancelling={cancellingCheckIds.includes(row.check.id)}
                        onCancel={cancelReportCheck}
                    />
                ))}
                {hidden.length > 0 && !showRetired && (
                    <LemonButton type="tertiary" size="xsmall" onClick={() => setShowRetired(true)}>
                        Show {hidden.length} more
                    </LemonButton>
                )}
            </div>
        </DetailSection>
    )
}
