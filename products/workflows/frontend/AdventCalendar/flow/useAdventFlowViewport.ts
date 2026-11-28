import { RefObject, useCallback, useLayoutEffect, useRef } from 'react'

import { AdventFlowFit, adventFlowFit } from './adventFlowFit'
import { AdventFlowLayout, AdventFlowRect } from './adventFlowLayout'

export interface AdventFlowViewport {
    fit: AdventFlowFit
    track: RefObject<HTMLDivElement>
    rectOnStage: (rect: AdventFlowRect) => AdventFlowRect
}

export function useAdventFlowViewport(
    stage: { width: number; height: number },
    layout: AdventFlowLayout,
    today: number
): AdventFlowViewport {
    const fit = adventFlowFit(stage, layout)
    const { zoom, box } = fit
    const track = useRef<HTMLDivElement>(null)
    const todayTop = layout.nodes.find((node) => node.door?.day === today)?.tile.y ?? 0
    const isColumn = layout.orientation === 'column'

    useLayoutEffect(() => {
        if (isColumn && track.current) {
            track.current.scrollTop = todayTop * zoom - stage.height / 2
        }
    }, [isColumn, todayTop, zoom, stage.height])

    const rectOnStage = useCallback(
        ({ x, y, width, height }: AdventFlowRect): AdventFlowRect => ({
            x: box.left + x * zoom,
            y: box.top + y * zoom - (track.current?.scrollTop ?? 0),
            width: width * zoom,
            height: height * zoom,
        }),
        [box.left, box.top, zoom]
    )

    return { fit, track, rectOnStage }
}
