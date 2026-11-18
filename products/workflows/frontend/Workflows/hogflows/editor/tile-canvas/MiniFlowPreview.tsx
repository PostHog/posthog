import type { RefObject } from 'react'

import type { HogFlow, HogFlowAction } from '../../types'
import { MINI_TILE_SIZE } from './MiniTile'
import { SpotlightCard } from './SpotlightCard'
import type { Point } from './tileCanvasModel'

const BRIDGE_HEIGHT = 22

/** The top padding is an invisible bridge over the gap, so moving down to the card keeps it open. */
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
    return (
        <div
            className="TileCanvas__appear absolute z-20 -translate-x-1/2"
            style={{ left: at.x + MINI_TILE_SIZE / 2, top: at.y + MINI_TILE_SIZE, paddingTop: BRIDGE_HEIGHT }}
            onMouseEnter={onEnter}
        >
            <div ref={previewRef}>
                <SpotlightCard action={action} workflow={workflow} count={count} showPreview={showPreview} />
            </div>
        </div>
    )
}
