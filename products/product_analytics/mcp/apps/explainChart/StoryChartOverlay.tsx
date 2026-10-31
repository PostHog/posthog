import { type ReactElement } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { StoryChartHighlight } from './StoryChartHighlight'
import { StoryChartMarker } from './StoryChartMarker'
import { StoryMarkerTails } from './StoryMarkerTails'
import { chapterBand, storyMarkers } from './storyOverlayGeometry'
import type { StoryPage } from './storyPages'

export interface StoryChartOverlayProps {
    seriesKey: string
    pages: StoryPage[]
    /** The page whose stretch is lit: the one on show, or the one the pointer is over. */
    highlightedIndex: number
    activeIndex: number
    showMarkers: boolean
    onSelect: (index: number) => void
}

export function StoryChartOverlay({
    seriesKey,
    pages,
    highlightedIndex,
    activeIndex,
    showMarkers,
    onSelect,
}: StoryChartOverlayProps): ReactElement | null {
    const layout = useChartLayout()
    const series = layout.series.find((candidate) => candidate.key === seriesKey)
    const highlighted = pages[highlightedIndex]
    if (!series || !highlighted) {
        return null
    }

    const band = chapterBand(layout, series, highlighted.range)
    const markers = showMarkers ? storyMarkers(layout, series, pages) : []
    return (
        <div data-attr="explain-chart-overlay">
            {band && (
                <StoryChartHighlight
                    band={band}
                    dimensions={layout.dimensions}
                    surface={layout.theme.backgroundColor ?? 'var(--card)'}
                />
            )}
            <StoryMarkerTails markers={markers} dimensions={layout.dimensions} activeIndex={activeIndex} />
            {markers.map((marker) => (
                <StoryChartMarker
                    key={marker.index}
                    marker={marker}
                    active={marker.index === activeIndex}
                    onSelect={onSelect}
                />
            ))}
        </div>
    )
}
