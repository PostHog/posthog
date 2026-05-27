import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { buildTheme } from 'lib/charts/utils/theme'
import { BoxPlot } from 'lib/hog-charts'
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

function quantile(sorted: number[], q: number): number {
    if (sorted.length === 1) {
        return sorted[0]
    }
    const pos = (sorted.length - 1) * q
    const lo = Math.floor(pos)
    const hi = Math.ceil(pos)
    return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

function ScorerOverview({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element | null {
    const { scorerScores, scorerHistogram } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    if (scorerScores.length === 0) {
        return null
    }
    const min = scorerScores[0]
    const max = scorerScores[scorerScores.length - 1]
    const avg = scorerScores.reduce((a, b) => a + b, 0) / scorerScores.length
    const median = quantile(scorerScores, 0.5)
    const p25 = quantile(scorerScores, 0.25)
    const p75 = quantile(scorerScores, 0.75)

    return (
        <OverviewPanel title="Score distribution" subtitle={`${scorerScores.length} scored`}>
            <ScoreBoxPlot
                min={min}
                p25={p25}
                median={median}
                mean={avg}
                p75={p75}
                max={max}
                scaleMin={scorerHistogram.scaleMin}
                scaleMax={scorerHistogram.scaleMax}
            />
            <div className="flex justify-between gap-4 text-xs text-muted tabular-nums pt-1 border-t">
                <span>min {min.toFixed(1)}</span>
                <span>median {median.toFixed(1)}</span>
                <span>avg {avg.toFixed(1)}</span>
                <span>max {max.toFixed(1)}</span>
            </div>
        </OverviewPanel>
    )
}

function ScoreBoxPlot({
    min,
    p25,
    median,
    mean,
    p75,
    max,
}: {
    min: number
    p25: number
    median: number
    mean: number
    p75: number
    max: number
    scaleMin: number
    scaleMax: number
}): JSX.Element {
    const theme = useMemo(() => buildTheme(), [])
    return (
        <div className="h-40 flex flex-col">
            <BoxPlot
                labels={['Scores']}
                series={[
                    {
                        key: 'scores',
                        label: 'Scores',
                        color: theme.colors[0],
                        data: [{ min, p25, median, mean, p75, max }],
                    },
                ]}
                config={{ showGrid: false }}
                theme={theme}
            />
        </div>
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
