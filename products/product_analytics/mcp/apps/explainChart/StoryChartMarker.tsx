/* eslint-disable react/forbid-dom-props -- pixel positions from the chart's scales */
import { type ReactElement } from 'react'

import { MARKER_SIZE, type StoryMarker } from './storyOverlayGeometry'

export interface StoryChartMarkerProps {
    marker: StoryMarker
    active: boolean
    onSelect: (index: number) => void
}

export function StoryChartMarker({ marker, active, onSelect }: StoryChartMarkerProps): ReactElement {
    const { page, index, center } = marker
    return (
        <button
            type="button"
            data-hog-charts-interactive-overlay
            data-attr="explain-chart-marker"
            aria-label={`Chapter ${index}: ${page.title}`}
            aria-current={active ? 'step' : undefined}
            className={`pointer-events-auto absolute flex cursor-pointer items-center justify-center rounded-full border text-xs font-medium tabular-nums transition-colors focus-visible:outline-2 focus-visible:outline-ring ${
                active
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-muted-foreground bg-card text-foreground hover:border-foreground'
            }`}
            style={{
                left: center.x - MARKER_SIZE / 2,
                top: center.y - MARKER_SIZE / 2,
                width: MARKER_SIZE,
                height: MARKER_SIZE,
            }}
            onClick={(event) => {
                event.stopPropagation()
                onSelect(index)
            }}
        >
            {index}
        </button>
    )
}
