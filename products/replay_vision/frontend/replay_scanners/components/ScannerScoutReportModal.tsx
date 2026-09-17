import './ScannerScoutReportModal.scss'
import './ScannerSummary.scss'

import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { urls } from 'scenes/urls'

import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'
import { ReportChartCard } from 'products/signals/frontend/inbox/components/detail/ReportChart'
import { resolveChartPlacements } from 'products/signals/frontend/inbox/utils/chartPlacement'
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

    const charts = (openedReport?.charts ?? []) as ReportChartApi[]
    const summary = openedReport?.summary || openedReport?.title || ''
    // The same parse the inbox uses, rather than a regex over the markdown: a reference inside a
    // code span or a table cell is not a placement, and getting that wrong draws a chart twice or
    // not at all.
    const placements = resolveChartPlacements(
        summary,
        charts.map((chart) => chart.chart_id)
    )
    const byId = new Map(charts.map((chart) => [chart.chart_id, chart]))
    const renderChartRef = (chartId: string, sourceOffset?: number): JSX.Element | null => {
        const chart = byId.get(chartId)
        return sourceOffset !== undefined && placements.inlineByOffset.get(sourceOffset) === chartId && chart ? (
            <ReportChartCard chart={chart} />
        ) : null
    }
    const trailingCharts = charts.filter((chart) => !placements.inlineIds.has(chart.chart_id))

    const loading = openedReportLoading || openedReport?.report_id !== openReportId

    return (
        <LemonModal
            isOpen
            onClose={closeReport}
            className="ScannerScoutReportModal"
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
                        <LemonMarkdown
                            className="ScannerSummaryMarkdown text-sm [&_[data-attr=report-chart]]:my-4"
                            disableImages
                            renderChartRef={renderChartRef}
                        >
                            {summary}
                        </LemonMarkdown>
                    </div>
                    {/* Whatever the prose never referenced. The inbox does the same. */}
                    {trailingCharts.map((chart) => (
                        <ReportChartCard key={chart.chart_id} chart={chart} />
                    ))}
                </div>
            )}
        </LemonModal>
    )
}
