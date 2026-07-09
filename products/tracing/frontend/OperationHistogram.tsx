import { useCallback, useMemo } from 'react'

import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'

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
}

// Duration buckets are categorical (1ms, 2ms, 5ms, ...) — the 1-2-5 series is already
// log-spaced, so a plain category axis renders it evenly (mirrors TracingSparkline).
function withCategoryXScale(scale: AnyScaleOptions): AnyScaleOptions {
    return {
        ...scale,
        type: 'category',
        ticks: {
            display: true,
            maxRotation: 0,
            maxTicksLimit: 8,
            font: {
                size: 10,
                lineHeight: 1,
            },
        },
    } as AnyScaleOptions
}

export function OperationHistogram({
    data,
    loading,
    selection,
    onSelect,
    onClear,
}: OperationHistogramProps): JSX.Element {
    const onSelectionChange = useCallback(
        ({ startIndex, endIndex }: { startIndex: number; endIndex: number }): void => {
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
        const startIndex = startIndexRaw === -1 ? 0 : startIndexRaw
        const endIndex = endIndexRaw === -1 ? bucketsNs.length : endIndexRaw
        if (startIndex >= endIndex) {
            return null
        }
        return { xMin: labels[startIndex], xMax: labels[endIndex] ?? labels[labels.length - 1] }
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
                        <LemonButton size="xsmall" type="tertiary" onClick={onClear}>
                            Clear
                        </LemonButton>
                    </>
                ) : (
                    <span className="text-xs text-muted italic">Drag to select a duration range</span>
                )}
            </div>
            <div className="relative h-32">
                {data.data.length > 0 ? (
                    <Sparkline
                        labels={data.labels}
                        data={data.data}
                        className="w-full h-full"
                        onSelectionChange={onSelectionChange}
                        withXScale={withCategoryXScale}
                        renderLabel={(label) => label}
                        tooltipRowCutoff={100}
                        hideZerosInTooltip
                        sortTooltipByCount
                        highlightedRange={highlightedRange}
                    />
                ) : !loading ? (
                    <div className="h-full text-muted flex items-center justify-center">No spans in this range</div>
                ) : null}
                {loading && <SpinnerOverlay />}
            </div>
        </div>
    )
}
