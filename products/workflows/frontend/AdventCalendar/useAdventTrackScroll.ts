import { RefObject, useCallback, useLayoutEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import { AdventGraph, adventDoorCenter } from './adventGraph'
import { AdventStageFit } from './useAdventStageFit'

export interface AdventTrackScrollProps {
    graph: AdventGraph
    today: number
    fit: AdventStageFit
    hasCard: boolean
    onScrollAway: () => void
}

export interface AdventTrackScroll {
    trackProps: { ref: RefObject<HTMLDivElement>; className: string; onScroll?: () => void }
    scrollLeft: () => number
}

export function useAdventTrackScroll({
    graph,
    today,
    fit: { zoom, stage, scrollsSideways },
    hasCard,
    onScrollAway,
}: AdventTrackScrollProps): AdventTrackScroll {
    const track = useRef<HTMLDivElement>(null)
    const todayDoor = graph.doors.find((door) => door.day === today)
    const todayX = todayDoor ? adventDoorCenter(todayDoor).x : 0

    useLayoutEffect(() => {
        if (scrollsSideways && track.current) {
            track.current.scrollLeft = todayX * zoom - stage.width / 2
        }
    }, [scrollsSideways, todayX, zoom, stage.width])

    const scrollLeft = useCallback((): number => track.current?.scrollLeft ?? 0, [])
    return {
        trackProps: {
            ref: track,
            className: cn('AdventStage__track', scrollsSideways && 'AdventStage__track--scrolls'),
            onScroll: hasCard ? onScrollAway : undefined,
        },
        scrollLeft,
    }
}
