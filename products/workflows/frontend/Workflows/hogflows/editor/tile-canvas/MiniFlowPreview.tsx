import { RefObject, useRef } from 'react'

import type { HogFlow, HogFlowAction } from '../../types'
import { MINI_TILE_SIZE } from './MiniTile'
import { SpotlightCard } from './SpotlightCard'
import type { Point } from './tileCanvasModel'
import { usePreviewPlacement } from './usePreviewPlacement'

const BRIDGE_HEIGHT = 22

/** The padding is an invisible bridge over the gap, so moving to the card keeps it open. */
export function MiniFlowPreview({
    at,
    action,
    workflow,
    count,
    showPreview,
    previewRef,
    onEnter,
}: {
    at: Point
    action: HogFlowAction
    workflow: HogFlow
    count: number | undefined
    showPreview: boolean
    previewRef: RefObject<HTMLDivElement>
    onEnter: () => void
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const placement = usePreviewPlacement(ref, MINI_TILE_SIZE)
    return (
        <div
            ref={ref}
            className="TileCanvas__appear absolute z-20"
            style={{
                left: at.x + MINI_TILE_SIZE / 2,
                top: placement.above ? at.y : at.y + MINI_TILE_SIZE,
                transform: `translate(calc(-50% + ${placement.x}px), ${placement.above ? '-100%' : '0'})`,
                ...(placement.above ? { paddingBottom: BRIDGE_HEIGHT } : { paddingTop: BRIDGE_HEIGHT }),
            }}
            onMouseEnter={onEnter}
        >
            <div ref={previewRef}>
                <SpotlightCard action={action} workflow={workflow} count={count} showPreview={showPreview} />
            </div>
        </div>
    )
}
