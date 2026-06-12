import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTag } from '@posthog/lemon-ui'
import { BarChart } from '@posthog/quill-charts'
import { buildTheme } from '@posthog/visualizations/charts/utils/theme'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerType } from '../types'
import { ScannerInsightsChart } from './ScannerInsightsChart'

function OverviewPanel({
    title,
    subtitle,
    disabled,
    children,
}: {
    title: string
    subtitle?: React.ReactNode
    disabled?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <div
            className={`border rounded p-4 space-y-3 ${
                disabled ? 'bg-surface-secondary opacity-60' : 'bg-surface-primary'
            }`}
        >
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{title}</span>
                {subtitle && <span className="text-xs text-muted tabular-nums">{subtitle}</span>}
            </div>
            {children}
        </div>
    )
}

function MonitorOverview({ scannerId }: { scannerId: string }): JSX.Element {
    const { monitorStats, hasActiveObservationFilters } = useValues(replayScannerLogic({ id: scannerId }))
    const { yesTotal, noTotal, inconclusiveTotal } = monitorStats
    const total = yesTotal + noTotal + inconclusiveTotal
    if (total === 0) {
        return (
            <OverviewPanel title="Verdict mix">
                <div className="text-muted text-sm">
                    {hasActiveObservationFilters ? 'No verdicts match the current filter.' : 'No verdicts yet.'}
                </div>
            </OverviewPanel>
        )
    }
    const yesPct = Math.round((yesTotal / total) * 100)
    const noPct = Math.round((noTotal / total) * 100)
    const inconclusivePct = Math.max(0, 100 - yesPct - noPct)

    return (
        <OverviewPanel title="Verdict mix" subtitle={`${total} verdict${total === 1 ? '' : 's'}`}>
            <LemonProgress percent={yesPct} />
            <div className="flex flex-wrap items-center gap-4 text-sm">
                <span className="flex items-center gap-2">
                    <LemonTag type="success">Yes</LemonTag>
                    <span className="tabular-nums">
                        {yesTotal} ({yesPct}%)
                    </span>
                </span>
                <span className="flex items-center gap-2">
                    <LemonTag type="default">No</LemonTag>
                    <span className="tabular-nums">
                        {noTotal} ({noPct}%)
                    </span>
                </span>
                {inconclusiveTotal > 0 && (
                    <span className="flex items-center gap-2">
                        <LemonTag type="muted">Inconclusive</LemonTag>
                        <span className="tabular-nums">
                            {inconclusiveTotal} ({inconclusivePct}%)
                        </span>
                    </span>
                )}
            </div>
        </OverviewPanel>
    )
}

function ClassifierOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, classifierTagStats, hasActiveObservationFilters } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const { fixedRanked, freeformRanked } = classifierTagStats
    // Wait for the scanner config — without it `freeformAllowed` defaults to `false` and the panel flashes the
    // "disabled" copy while the config is still loading.
    if (!scanner || scanner.scanner_type !== 'classifier') {
        return null
    }
    const freeformAllowed = !!scanner.scanner_config.allow_freeform_tags
    const fixedEmpty = hasActiveObservationFilters
        ? 'No fixed-vocabulary tags match the current filter.'
        : 'No fixed-vocabulary tags emitted yet.'
    const freeformEmpty = hasActiveObservationFilters
        ? 'No freeform tags match the current filter.'
        : 'No freeform tags emitted yet.'

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
                {renderRanked(fixedRanked, fixedEmpty)}
            </OverviewPanel>

            <OverviewPanel
                title="Top freeform tags"
                subtitle={freeformAllowed ? 'outside configured vocabulary' : 'disabled'}
                disabled={!freeformAllowed}
            >
                {freeformAllowed ? (
                    renderRanked(freeformRanked, freeformEmpty)
                ) : (
                    <div className="text-muted text-sm">
                        Freeform tags are disabled for this scanner — the model can only pick from your configured
                        vocabulary. Enable "Allow freeform tags" in the scanner config to let it propose new ones.
                    </div>
                )}
            </OverviewPanel>
        </div>
    )
}

function ScorerOverview({ scannerId }: { scannerId: string }): JSX.Element {
    const { scorerSummary, scorerHistogram, hasActiveObservationFilters } = useValues(
        replayScannerLogic({ id: scannerId })
    )
    const theme = useMemo(() => buildTheme(), [])
    if (!scorerSummary || !scorerHistogram) {
        return (
            <OverviewPanel title="Score distribution">
                <div className="text-muted text-sm">
                    {hasActiveObservationFilters
                        ? 'No scored observations match the current filter.'
                        : 'No scored observations yet.'}
                </div>
            </OverviewPanel>
        )
    }
    return (
        <OverviewPanel title="Score distribution" subtitle={`${scorerSummary.count} scored`}>
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

export function ScannerOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    if (!scanner) {
        return null
    }
    const scannerType: ScannerType = scanner.scanner_type
    // Summarizer panel deferred to the Max chat follow-up.
    const typeOverview =
        scannerType === 'monitor' ? (
            <MonitorOverview scannerId={scannerId} />
        ) : scannerType === 'classifier' ? (
            <ClassifierOverview scannerId={scannerId} />
        ) : scannerType === 'scorer' ? (
            <ScorerOverview scannerId={scannerId} />
        ) : null
    const showChart = scannerType !== 'summarizer'
    if (!showChart && !typeOverview) {
        return null
    }
    return (
        <div className="space-y-4">
            {showChart && <ScannerInsightsChart scannerId={scannerId} scannerType={scannerType} />}
            {typeOverview}
        </div>
    )
}
