import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { buildTheme } from 'lib/charts/utils/theme'
import { BarChart } from 'lib/hog-charts'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerType } from '../types'
import { ScannerInsightsChart } from './ScannerInsightsChart'

function OverviewPanel({
    title,
    subtitle,
    children,
}: {
    title: string
    subtitle?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{title}</span>
                {subtitle && <span className="text-xs text-muted tabular-nums">{subtitle}</span>}
            </div>
            {children}
        </div>
    )
}

function MonitorOverview({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element | null {
    const { monitorStats } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    const { yesTotal, noTotal } = monitorStats
    const total = yesTotal + noTotal
    if (total === 0) {
        return null
    }
    const yesPct = Math.round((yesTotal / total) * 100)

    return (
        <OverviewPanel title="Verdict mix" subtitle={`${total} verdict${total === 1 ? '' : 's'}`}>
            <LemonProgress percent={yesPct} />
            <div className="flex items-center gap-4 text-sm">
                <span className="flex items-center gap-2">
                    <LemonTag type="success">Yes</LemonTag>
                    <span className="tabular-nums">
                        {yesTotal} ({yesPct}%)
                    </span>
                </span>
                <span className="flex items-center gap-2">
                    <LemonTag type="default">No</LemonTag>
                    <span className="tabular-nums">
                        {noTotal} ({100 - yesPct}%)
                    </span>
                </span>
            </div>
        </OverviewPanel>
    )
}

function ClassifierOverview({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element | null {
    const { classifierTagStats } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    const { fixedRanked, freeformRanked, totalWithTags } = classifierTagStats
    if (totalWithTags === 0) {
        return null
    }

    const renderRanked = (ranked: [string, number][], emptyMessage: string): JSX.Element => {
        if (ranked.length === 0) {
            return <div className="text-muted text-sm">{emptyMessage}</div>
        }
        const maxCount = ranked[0][1]
        return (
            <div className="space-y-1.5">
                {ranked.map(([tag, count]) => (
                    <div key={tag} className="flex items-center gap-2">
                        <LemonTag type="option" className="shrink-0">
                            {tag}
                        </LemonTag>
                        <LemonProgress percent={Math.round((count / maxCount) * 100)} />
                        <span className="text-xs text-muted tabular-nums w-8 text-right">{count}</span>
                    </div>
                ))}
            </div>
        )
    }

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OverviewPanel title="Top fixed tags" subtitle="from configured vocabulary">
                {renderRanked(fixedRanked, 'No fixed-vocabulary tags emitted yet.')}
            </OverviewPanel>

            <OverviewPanel title="Top freeform tags" subtitle="outside configured vocabulary">
                {renderRanked(freeformRanked, 'No freeform tags emitted.')}
            </OverviewPanel>
        </div>
    )
}

function ScorerOverview({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element | null {
    const { scorerScores, scorerSummary, scorerHistogram } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    const theme = useMemo(() => buildTheme(), [])
    if (!scorerSummary || !scorerHistogram) {
        return null
    }
    return (
        <OverviewPanel title="Score distribution" subtitle={`${scorerScores.length} scored`}>
            <div className="h-40 flex flex-col">
                <BarChart
                    labels={scorerHistogram.labels}
                    series={[{ key: 'count', label: 'Sessions', color: theme.colors[0], data: scorerHistogram.counts }]}
                    config={{ showGrid: false }}
                    theme={theme}
                />
            </div>
            <div className="flex justify-between gap-4 text-xs text-muted tabular-nums pt-1 border-t">
                <span>min {scorerSummary.min.toFixed(1)}</span>
                <span>median {scorerSummary.median.toFixed(1)}</span>
                <span>avg {scorerSummary.mean.toFixed(1)}</span>
                <span>max {scorerSummary.max.toFixed(1)}</span>
            </div>
        </OverviewPanel>
    )
}

export function ScannerOverview({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element | null {
    const { scanner, coverageStats } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    if (!scanner) {
        return null
    }
    const scannerType: ScannerType = scanner.scanner_type
    // Summarizer panel deferred to the Max chat follow-up.
    const typeOverview =
        scannerType === 'monitor' ? (
            <MonitorOverview scannerId={scannerId} tabId={tabId} />
        ) : scannerType === 'classifier' ? (
            <ClassifierOverview scannerId={scannerId} tabId={tabId} />
        ) : scannerType === 'scorer' ? (
            <ScorerOverview scannerId={scannerId} tabId={tabId} />
        ) : null
    if (!typeOverview && scannerType !== 'summarizer') {
        return null
    }
    const showChart = scannerType !== 'summarizer'
    const showCoverage = coverageStats.totalSessions > 0
    if (!showCoverage && !showChart && !typeOverview) {
        return null
    }
    return (
        <div className="space-y-4">
            {showCoverage && (
                <div className="text-xs text-muted tabular-nums">
                    Scanned <span className="font-semibold text-default">{coverageStats.recentSessions}</span> session
                    {coverageStats.recentSessions === 1 ? '' : 's'} in the last {coverageStats.recentDays} days ·{' '}
                    <span className="font-semibold text-default">{coverageStats.totalSessions}</span> total
                </div>
            )}
            {showChart && <ScannerInsightsChart scannerId={scannerId} scannerType={scannerType} tabId={tabId} />}
            {typeOverview}
        </div>
    )
}
