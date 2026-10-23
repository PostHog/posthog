/* eslint-disable react/forbid-dom-props -- pixel positions from the chart's scales */
import { type ReactElement } from 'react'

import type { ChartDimensions } from '@posthog/quill-charts'

import { type StoryMarker, tailPoints } from './storyOverlayGeometry'

export interface StoryMarkerTailsProps {
    markers: StoryMarker[]
    dimensions: ChartDimensions
    activeIndex: number
}

export function StoryMarkerTails({ markers, dimensions, activeIndex }: StoryMarkerTailsProps): ReactElement {
    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    return (
        <svg
            className="pointer-events-none absolute overflow-visible"
            style={{ left: plotLeft, top: plotTop, width: plotWidth, height: plotHeight }}
            aria-hidden
        >
            {markers.map((marker) => (
                <polygon
                    key={marker.index}
                    points={tailPoints(marker, dimensions)}
                    fill={marker.index === activeIndex ? 'var(--foreground)' : 'var(--muted-foreground)'}
                />
            ))}
        </svg>
    )
}
