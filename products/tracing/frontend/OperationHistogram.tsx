import { useCallback, useMemo } from 'react'

import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'
import {
    BarChart,
    type BarChartConfig,
    type DateRangeZoomData,
    DefaultTooltip,
    HighlightedRange,
    type Series,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    formatBucketLabel,
    selectionToDurationRange,
    snapDurationToBucket,
    type TracingDurationHistogramData,
} from './durationBuckets'
import type { DurationRange } from './operationFilters'

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
    const config = useChartConfig<BarChartConfig>(() => ({}), [])

    const series = useMemo<Series[]>(
        () =>
            data.data.map((s) => ({
                key: s.name,
                label: s.name,
                data: s.values,
                color: getColorVar(s.color),
            })),
        [data.data]
    )

    const onSelectionChange = useCallback(
        ({ startIndex, endIndex }: DateRangeZoomData): void => {
            const range = selectionToDurationRange(data.bucketsNs, startIndex, endIndex)
            if (range) {
                onSelect(range)
            }
        },
        [data.bucketsNs, onSelect]
    )

    // Map the persisted selection back onto bucket indices: snap each edge onto the same
    // 1-2-5 series the backend bucketed with, then find those buckets on the axis.
    const highlightedRange = useMemo(() => {
        if (!selection || data.bucketsNs.length === 0) {
            return null
        }
        const { bucketsNs, labels } = data
        const startIndexRaw = bucketsNs.indexOf(snapDurationToBucket(selection.minNs))
        // maxNs is the exclusive upper edge — the highlight ends at the bar before it.
        const endIndexRaw = bucketsNs.indexOf(snapDurationToBucket(selection.maxNs))
        const startIndex = startIndexRaw !== -1 ? startIndexRaw : selection.minNs <= bucketsNs[0] ? 0 : bucketsNs.length
        const endIndex =
            endIndexRaw !== -1 ? endIndexRaw : selection.maxNs > bucketsNs[bucketsNs.length - 1] ? bucketsNs.length : 0
        if (startIndex >= endIndex) {
            return null
        }
        return { start: labels[startIndex], end: labels[endIndex - 1] ?? labels[labels.length - 1] }
    }, [selection, data])

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
                    <BarChart
                        series={series}
                        labels={data.labels}
                        theme={theme}
                        config={config}
                        onDateRangeZoom={onSelectionChange}
                        tooltip={(ctx) => (
                            <DefaultTooltip
                                {...ctx}
                                hideZeroRows
                                sortedByValue
                                valueFormatter={(value) => humanFriendlyNumber(value)}
                            />
                        )}
                    >
                        {highlightedRange && (
                            <HighlightedRange start={highlightedRange.start} end={highlightedRange.end} />
                        )}
                    </BarChart>
                ) : !loading ? (
                    <div className="h-full text-muted flex items-center justify-center">No spans in this range</div>
                ) : null}
                {loading && <SpinnerOverlay />}
            </div>
        </div>
    )
}
