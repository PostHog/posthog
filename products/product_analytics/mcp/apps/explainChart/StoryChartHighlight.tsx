/* eslint-disable react/forbid-dom-props -- pixel positions from the chart's scales */
import { type ReactElement } from 'react'

import type { ChartDimensions } from '@posthog/quill-charts'

import { type Band, dimsAround } from './storyOverlayGeometry'

// The brand orange in both themes, so the highlight never reads as one of the chart's series.
const HIGHLIGHT_COLOR = 'var(--primary-light)'
const FEATHER = 28

const tint = (share: number): string => `color-mix(in srgb, ${HIGHLIGHT_COLOR} ${share}%, transparent)`

export interface StoryChartHighlightProps {
    band: Band
    dimensions: ChartDimensions
    /** The chart's background, which the dimmed sides fade into. */
    surface: string
}

export function StoryChartHighlight({ band, dimensions, surface }: StoryChartHighlightProps): ReactElement {
    const { plotTop, plotHeight } = dimensions
    return (
        <>
            {dimsAround(band, dimensions).map((dim, index) => {
                const width = Math.max(dim.right - dim.left, 0)
                const feather = Math.min(FEATHER, width / 2)
                return (
                    <div
                        key={index}
                        className="pointer-events-none absolute opacity-65 transition-[left,width] duration-500 ease-out motion-reduce:transition-none starting:opacity-0"
                        style={{
                            left: dim.left,
                            top: plotTop,
                            width,
                            height: plotHeight,
                            background: `linear-gradient(to right, ${dim.fadeLeft ? 'transparent' : surface}, ${surface} ${feather}px, ${surface} calc(100% - ${feather}px), ${dim.fadeRight ? 'transparent' : surface})`,
                        }}
                    />
                )
            })}
            <div
                className="pointer-events-none absolute rounded-t-md border-x border-t-2 transition-[left,width] duration-500 ease-out motion-reduce:transition-none starting:opacity-0"
                style={{
                    left: band.left,
                    top: plotTop,
                    width: band.right - band.left,
                    height: plotHeight,
                    borderColor: tint(45),
                    borderTopColor: HIGHLIGHT_COLOR,
                    background: `linear-gradient(to bottom, ${tint(20)}, ${tint(5)})`,
                }}
            />
        </>
    )
}
