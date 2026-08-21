import './ScannerSummary.scss'

import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { urls } from 'scenes/urls'

import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'
import { ReportChartCard } from 'products/signals/frontend/inbox/components/detail/ReportChart'
import { prettifyScoutSkillName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import { scannerScoutLogic } from '../scannerScoutLogic'

/** One filed report, read in place. Deliberately not the full record: the inbox owns status,
 * priority, reviewers and the run trail, and this links there rather than restating it. */
export function ScannerScoutReportModal({
    scannerId,
    scannerName,
}: {
    scannerId: string
    scannerName: string
}): JSX.Element | null {
    const logic = scannerScoutLogic({ scannerId, scannerName })
    const { openReportId, openedReport, openedReportLoading } = useValues(logic)
    const { closeReport } = useActions(logic)

    if (!openReportId) {
        return null
    }

    const loading = openedReportLoading || openedReport?.report_id !== openReportId

    return (
        <LemonModal
            isOpen
            onClose={closeReport}
            width={720}
            title={loading ? 'Report' : openedReport?.title || 'Untitled report'}
            description={
                loading ? undefined : (
                    <span>
                        {prettifyScoutSkillName(openedReport?.skill_name ?? '')} · filed{' '}
                        <TZLabel time={openedReport?.filed_at ?? ''} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                    </span>
                )
            }
            footer={
                !loading &&
                openedReport && (
                    <LemonButton
                        type="secondary"
                        to={urls.inboxReport('reports', openedReport.report_id)}
                        data-attr="vision-scout-report-open-inbox"
                    >
                        Open in inbox
                    </LemonButton>
                )
            }
        >
            {loading ? (
                <LemonSkeleton className="h-40 w-full" />
            ) : (
                <div className="flex flex-col gap-3">
                    <div className="rounded bg-surface-secondary px-3 py-2">
                        {/* Agent-written content derived from recordings: render non-PostHog images
                            as links, not auto-fetched <img>s. */}
                        <LemonMarkdown className="ScannerSummaryMarkdown text-sm" disableImages>
                            {openedReport?.summary || openedReport?.title || ''}
                        </LemonMarkdown>
                    </div>
                    {/* Rendered after the body rather than placed inline: the summary's
                        `[label](chart:<id>)` links are what the inbox uses to position them, and
                        that placement machinery lives with the inbox's own report view. */}
                    {(openedReport?.charts ?? []).map((chart) => (
                        <ReportChartCard key={chart.chart_id} chart={chart as ReportChartApi} />
                    ))}
                </div>
            )}
        </LemonModal>
    )
}
