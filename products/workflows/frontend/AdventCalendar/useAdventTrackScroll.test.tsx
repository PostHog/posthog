import { render } from '@testing-library/react'
import { createRef } from 'react'

import { drawAdventRewards } from './adventDraw'
import { adventDoorCenter, buildAdventGraph, EMPTY_ADVENT_PROGRESS } from './adventGraph'
import { AdventTrackScrollProps, useAdventTrackScroll } from './useAdventTrackScroll'

function Track(props: AdventTrackScrollProps): JSX.Element {
    const { trackProps } = useAdventTrackScroll(props)
    return <div ref={trackProps.ref} />
}

function propsOf(today: number, zoom: number, height: number): AdventTrackScrollProps {
    return {
        graph: buildAdventGraph(EMPTY_ADVENT_PROGRESS, today, drawAdventRewards('seed')),
        today,
        fit: {
            ref: createRef(),
            stage: { width: 390, height },
            zoom,
            box: { left: 0, top: 0, width: 1000, height },
            scrollsSideways: true,
        },
        hasCard: false,
        onScrollAway: () => {},
    }
}

function centerOf(today: number, zoom: number): number {
    const door = propsOf(today, zoom, 700).graph.doors.find((candidate) => candidate.day === today)!
    return adventDoorCenter(door).x * zoom - 390 / 2
}

describe('useAdventTrackScroll', () => {
    it("keeps the swiped-to spot in the middle when the stage resizes, and centers the new day's door when the day changes", () => {
        const { container, rerender } = render(<Track {...propsOf(3, 0.5, 700)} />)
        const track = container.firstElementChild!
        const middleOfPicture = (zoom: number): number => (track.scrollLeft + 390 / 2) / zoom
        expect(track.scrollLeft).toBe(centerOf(3, 0.5))

        track.scrollLeft = 300
        const swipedTo = middleOfPicture(0.5)
        rerender(<Track {...propsOf(3, 0.45, 640)} />)
        expect(middleOfPicture(0.45)).toBeCloseTo(swipedTo)

        rerender(<Track {...propsOf(4, 0.45, 640)} />)
        expect(track.scrollLeft).toBe(centerOf(4, 0.45))
    })
})
