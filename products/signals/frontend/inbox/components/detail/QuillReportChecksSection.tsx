import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTarget } from '@posthog/icons'
import { Button, Skeleton, Text } from '@posthog/quill'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { QuillDetailSection } from './QuillDetailSection'
import { QuillReportCheckRow } from './QuillReportCheckRow'
import {
    buildReportCheckRows,
    latestCheckExplanations,
    reportChecksMeta,
    splitReportCheckRows,
} from './reportCheckPresentation'

/** The quill sibling of `ReportChecksSection`. Hidden entirely when the report has no checks. */
export function QuillReportChecksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportChecks, reportChecksLoading, reportArtefacts, cancellingCheckIds } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const { cancelReportCheck } = useActions(inboxReportDetailLogic({ reportId: report.id, report }))
    const { openReportCheckMetricSuggestion } = useActions(inboxTaskKickoffLogic)
    const { aiConsentDisabledReason, metricCheckReplacementDisabledReason, isCreatingPr, isDiscussing } =
        useValues(inboxTaskKickoffLogic)
    const [showRetired, setShowRetired] = useState(false)

    if (reportChecksLoading && !reportChecks) {
        return (
            <QuillDetailSection icon={<IconTarget />} title="Follow-up checks" collapsible>
                <Skeleton className="h-12 w-full" />
            </QuillDetailSection>
        )
    }

    if (!reportChecks || reportChecks.length === 0) {
        return null
    }

    const rows = buildReportCheckRows(reportChecks, latestCheckExplanations(reportArtefacts ?? []), report.status)
    const { visible, hidden } = splitReportCheckRows(rows)

    return (
        <QuillDetailSection
            icon={<IconTarget />}
            title="Follow-up checks"
            collapsible
            meta={
                <Text size="xs" render={<span />} className="text-subtle-foreground tabular-nums">
                    {reportChecksMeta(reportChecks, report.status)}
                </Text>
            }
        >
            <div className="flex flex-col gap-1.5">
                {(showRetired ? rows : visible).map((row) => (
                    <QuillReportCheckRow
                        key={row.check.id}
                        row={row}
                        cancelling={cancellingCheckIds.includes(row.check.id)}
                        onCancel={cancelReportCheck}
                        onSuggestMetric={() => openReportCheckMetricSuggestion(report, row.check)}
                        suggestionDisabledReason={
                            aiConsentDisabledReason ??
                            metricCheckReplacementDisabledReason ??
                            (isCreatingPr || isDiscussing ? 'Wait for the task to start.' : null)
                        }
                    />
                ))}
                {hidden.length > 0 && !showRetired && (
                    <Button className="self-start" onClick={() => setShowRetired(true)}>
                        Show {hidden.length} more
                    </Button>
                )}
            </div>
        </QuillDetailSection>
    )
}
