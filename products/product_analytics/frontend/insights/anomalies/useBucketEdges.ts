import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

/**
 * Returns the left and right pixel edges of a bucket, or null when its label does not resolve. Unclipped, so an edge
 * can fall outside the plot. Renders inside a quill chart.
 */
export function useBucketEdges(): (index: number) => [number, number] | null {
    const { scales, dimensions, labels } = useChartLayout()
    const { x, extent } = scales
    const { plotWidth } = dimensions

    return useMemo(() => {
        const centre = (index: number): number | null => {
            const label = labels[index]
            const position = label != null ? x(label) : undefined
            return position != null && isFinite(position) ? position : null
        }
        return (index) => {
            const middle = centre(index)
            if (middle == null) {
                return null
            }
            // A bar chart gives a bucket its band width. A line chart has only points, so a bucket takes the space
            // between the midpoints to its neighbours, and an end bucket mirrors the space on its inner side.
            const bandWidth = extent?.(labels[index])
            if (bandWidth) {
                return [middle - bandWidth / 2, middle + bandWidth / 2]
            }
            const previous = centre(index - 1)
            const next = centre(index + 1)
            const leftHalf =
                previous != null ? (middle - previous) / 2 : next != null ? (next - middle) / 2 : plotWidth / 2
            const rightHalf = next != null ? (next - middle) / 2 : leftHalf
            return [middle - leftHalf, middle + rightHalf]
        }
    }, [x, extent, labels, plotWidth])
}
