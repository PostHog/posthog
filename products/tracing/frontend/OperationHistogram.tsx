import { useCallback, useMemo } from 'react'

import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'

import {
    formatBucketLabel,
    selectionToDurationRange,
    snapDurationToBucket,
    type TracingDurationHistogramData,
} from './durationBuckets'
import type { DurationRange } from './operationFilters'
import { categoryDurationXScale } from './TracingSparkline'

interface OperationHistogramProps {
    data: TracingDurationHistogramData
    loading: boolean
    selection: DurationRange | null
    onSelect: (selection: DurationRange) => void
    onClear: () => void
    /** Clearing the selection refetches samples — disable the button while that's in flight. */
    samplesLoading?: boolean
}

export function OperationHistogram({
    data,
    loading,
    selection,
    onSelect,
    onClear,
    samplesLoading = false,
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
        // An off-axis edge clamps toward its near end; a selection entirely off the axis
        // (e.g. persisted before a date change reshaped the distribution) collapses to
        // start >= end and renders no highlight.
        const startIndex = startIndexRaw !== -1 ? startIndexRaw : selection.minNs <= bucketsNs[0] ? 0 : bucketsNs.length
        const endIndex =
            endIndexRaw !== -1 ? endIndexRaw : selection.maxNs > bucketsNs[bucketsNs.length - 1] ? bucketsNs.length : 0
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
            </div>
            <div className="relative h-32">
                {data.data.length > 0 ? (
                    <Sparkline
                        labels={data.labels}
                        data={data.data}
                        className="w-full h-full"
                        onSelectionChange={onSelectionChange}
                        withXScale={categoryDurationXScale}
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
