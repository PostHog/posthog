import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonSegmentedButton, type LemonSegmentedButtonOption, LemonTag } from '@posthog/lemon-ui'
import {
    BarChart,
    type BarChartConfig,
    Heatmap,
    type HeatmapConfig,
    type Series,
    SlopeChart,
    type SlopeChartConfig,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { SCANNER_TYPE_TAG_TYPE, type ScannerType, scannerTypeLabel } from '../types'

interface TimeSeriesLineVisualization {
    kind: 'time-series-line'
    labels: string[]
    series: Series[]
    config: TimeSeriesLineChartConfig
}

interface TimeSeriesBarVisualization {
    kind: 'time-series-bar'
    labels: string[]
    series: Series[]
    config: TimeSeriesBarChartConfig
}

interface BarVisualization {
    kind: 'bar'
    labels: string[]
    series: Series[]
    config: BarChartConfig
}

interface SlopeVisualization {
    kind: 'slope'
    labels: string[]
    series: Series[]
    config: SlopeChartConfig
}

interface HeatmapVisualization {
    kind: 'heatmap'
    xLabels: string[]
    yLabels: string[]
    cells: number[][]
    config: HeatmapConfig
}

export type ReplayVisionVisualizationChart =
    | TimeSeriesLineVisualization
    | TimeSeriesBarVisualization
    | BarVisualization
    | SlopeVisualization
    | HeatmapVisualization

export interface ReplayVisionVisualizationView {
    key: string
    label: string
    tooltip: string
    description: string
    callout: string
    chart: ReplayVisionVisualizationChart
}

export interface ReplayVisionScannerVisualizationExample {
    key: string
    scannerType: ScannerType
    name: string
    description: string
    observationCount: number
    outputLabel: string
    views: ReplayVisionVisualizationView[]
}

export interface ReplayVisionVisualizationPrototypeProps {
    initialScannerKey: string
    examples: ReplayVisionScannerVisualizationExample[]
}

const CHART_DATA_ATTR = 'replay-vision-visualization-chart'

export function ReplayVisionVisualizationPrototype({
    initialScannerKey,
    examples,
}: ReplayVisionVisualizationPrototypeProps): JSX.Element {
    const theme = useChartTheme()
    const initialExample = examples.find((example) => example.key === initialScannerKey) ?? examples[0]
    const [scannerKey, setScannerKey] = useState(initialExample?.key ?? '')
    const [viewKey, setViewKey] = useState(initialExample?.views[0]?.key ?? '')
    const activeExample = examples.find((example) => example.key === scannerKey) ?? examples[0]
    const activeView = activeExample?.views.find((view) => view.key === viewKey) ?? activeExample?.views[0]

    if (!activeExample || !activeView) {
        return <div className="rounded border bg-surface-primary p-4 text-sm text-muted">No examples to show.</div>
    }

    const scannerOptions: LemonSegmentedButtonOption<string>[] = examples.map((example) => ({
        value: example.key,
        label: scannerTypeLabel(example.scannerType),
        tooltip: example.name,
        // These values are stable interaction contracts for Storybook and visual tests.
        'data-attr': `replay-vision-visualization-scanner-${example.key}`,
    }))
    const viewOptions: LemonSegmentedButtonOption<string>[] = activeExample.views.map((view) => ({
        value: view.key,
        label: view.label,
        tooltip: view.tooltip,
        'data-attr': `replay-vision-visualization-view-${view.key}`,
    }))

    const selectScanner = (nextScannerKey: string): void => {
        const nextExample = examples.find((example) => example.key === nextScannerKey)
        setScannerKey(nextScannerKey)
        setViewKey(nextExample?.views[0]?.key ?? '')
    }

    const chart = (): JSX.Element => {
        const visualization = activeView.chart
        if (visualization.kind === 'time-series-line') {
            return (
                <TimeSeriesLineChart
                    dataAttr={CHART_DATA_ATTR}
                    labels={visualization.labels}
                    series={visualization.series}
                    theme={theme}
                    config={visualization.config}
                />
            )
        }
        if (visualization.kind === 'time-series-bar') {
            return (
                <TimeSeriesBarChart
                    dataAttr={CHART_DATA_ATTR}
                    labels={visualization.labels}
                    series={visualization.series}
                    theme={theme}
                    config={visualization.config}
                />
            )
        }
        if (visualization.kind === 'bar') {
            return (
                <BarChart
                    dataAttr={CHART_DATA_ATTR}
                    labels={visualization.labels}
                    series={visualization.series}
                    theme={theme}
                    config={visualization.config}
                />
            )
        }
        if (visualization.kind === 'slope') {
            return (
                <SlopeChart
                    dataAttr={CHART_DATA_ATTR}
                    labels={visualization.labels}
                    series={visualization.series}
                    theme={theme}
                    config={visualization.config}
                />
            )
        }
        return (
            <Heatmap
                dataAttr={CHART_DATA_ATTR}
                xLabels={visualization.xLabels}
                yLabels={visualization.yLabels}
                cells={visualization.cells}
                theme={theme}
                config={visualization.config}
            />
        )
    }

    return (
        <div className="@container/replay-vision-visualization space-y-4">
            <div className="rounded border bg-surface-primary p-4 space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <h1 className="m-0 text-base font-semibold">Scanner visualization examples</h1>
                            <LemonTag type="muted">Dummy data</LemonTag>
                        </div>
                        <p className="m-0 text-sm text-muted">
                            Compare useful views for each kind of result Replay Vision produces.
                        </p>
                    </div>
                    <div className="w-full @min-[48rem]/replay-vision-visualization:max-w-2xl">
                        <LemonSegmentedButton
                            fullWidth
                            size="small"
                            value={activeExample.key}
                            onChange={selectScanner}
                            options={scannerOptions}
                        />
                    </div>
                </div>
            </div>

            <div className="rounded border bg-surface-primary p-4 space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <h2 className="m-0 text-sm font-semibold">{activeExample.name}</h2>
                            <LemonTag type={SCANNER_TYPE_TAG_TYPE[activeExample.scannerType]}>
                                {scannerTypeLabel(activeExample.scannerType)}
                            </LemonTag>
                        </div>
                        <p className="m-0 max-w-2xl text-xs text-muted">{activeExample.description}</p>
                        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted tabular-nums">
                            <span>{activeExample.observationCount.toLocaleString()} observations</span>
                            <span>Existing output: {activeExample.outputLabel}</span>
                        </div>
                    </div>
                    <div className="w-full @min-[48rem]/replay-vision-visualization:max-w-2xl">
                        <LemonSegmentedButton
                            fullWidth
                            size="xsmall"
                            value={activeView.key}
                            onChange={setViewKey}
                            options={viewOptions}
                        />
                    </div>
                </div>

                <div className="h-96 flex flex-col">{chart()}</div>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
                    <p className="m-0 max-w-3xl text-xs text-muted">{activeView.description}</p>
                    <LemonTag type="highlight" icon={<IconSparkles />}>
                        {activeView.callout}
                    </LemonTag>
                </div>
            </div>
        </div>
    )
}
