import { useCallback, useMemo } from 'react'

import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'
import {
    Histogram,
    type HistogramBin,
    type HistogramConfig,
    type HistogramRange,
    type HistogramSeries,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'

import { bucketUpperBound, formatBucketLabel, type TracingDurationHistogramData } from './durationBuckets'
import type { DurationRange } from './operationFilters'

const HISTOGRAM_CONFIG: HistogramConfig = { xAxis: { scaleType: 'log', format: 'duration_ns' } }

interface OperationHistogramProps {
    data: TracingDurationHistogramData
    loading: boolean
    selection: DurationRange | null
    onSelect: (selection: DurationRange) => void
    onClear: () => void
    /** Clearing the selection refetches samples — disable the button while that's in flight. */
    samplesLoading?: boolean
    /** Extra header content, right-aligned (e.g. the histogram/heatmap chart toggle). */
    actions?: React.ReactNode
}

export function OperationHistogram({
    data,
    loading,
    selection,
    onSelect,
    onClear,
    samplesLoading = false,
    actions,
}: OperationHistogramProps): JSX.Element {
    const theme = useChartTheme()

    const bins = useMemo<HistogramBin[]>(
        () => data.bucketsNs.map((start) => ({ start, end: bucketUpperBound(start) })),
        [data.bucketsNs]
    )
    const series = useMemo<HistogramSeries[]>(
        () => data.data.map((s) => ({ key: s.name, label: s.name, data: s.values, color: getColorVar(s.color) })),
        [data.data]
    )
    const selectedRange = useMemo<HistogramRange | null>(
        () => (selection ? { min: selection.minNs, max: selection.maxNs } : null),
        [selection]
    )
    const onRangeSelect = useCallback(
        ({ min, max }: HistogramRange): void => onSelect({ minNs: min, maxNs: max }),
        [onSelect]
    )

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 min-h-6">
                <span className="text-xs text-muted">Latency distribution</span>
                {selection ? (
                    <>
                        <span className="text-xs font-mono">
                            {formatBucketLabel(selection.minNs)} – {formatBucketLabel(selection.maxNs)}
                        </span>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={onClear}
                            disabledReason={samplesLoading ? 'Loading samples…' : undefined}
                        >
                            Clear
                        </LemonButton>
                    </>
                ) : (
                    <span className="text-xs text-muted italic">Drag to select a duration range</span>
                )}
                {actions && <div className="ml-auto">{actions}</div>}
            </div>
            <div className="relative h-32 flex flex-col">
                {data.data.length > 0 ? (
                    <Histogram
                        bins={bins}
                        series={series}
                        theme={theme}
                        config={HISTOGRAM_CONFIG}
                        selectedRange={selectedRange}
                        onRangeSelect={onRangeSelect}
                        onRangeClear={samplesLoading ? undefined : onClear}
                    />
                ) : !loading ? (
                    <div className="h-full text-muted flex items-center justify-center">No spans in this range</div>
                ) : null}
                {loading && <SpinnerOverlay />}
            </div>
        </div>
    )
}
