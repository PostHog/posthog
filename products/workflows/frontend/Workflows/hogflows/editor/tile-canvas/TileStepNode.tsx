import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow, HogFlowAction } from '../../types'
import { TileAttentionMarker } from './TileAttentionMarker'
import { tileCanvasLogic } from './tileCanvasLogic'
import { hasStepMenu } from './tileCanvasModel'
import { TileCaption } from './TileCaption'
import { TileFace } from './TileFace'
import { HOVER_CARD_CLOSE_MS, HOVER_CARD_OPEN_DELAY_MS, TileHoverCard } from './TileHoverCard'
import { TileStepMenu } from './TileStepMenu'
import { useHoverIntent } from './useHoverIntent'
import { useRaisedNode } from './useRaisedNode'
import { useTileStep } from './useTileStep'

export function TileStepNode({
    action,
    workflow,
    count,
    selected = false,
    menuOpen = false,
    interactive = true,
}: {
    action: HogFlowAction
    workflow: HogFlow
    count: number | undefined
    selected?: boolean
    menuOpen?: boolean
    interactive?: boolean
}): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    const tile = useTileStep(action, workflow)
    const hover = useHoverIntent(interactive && !selected && !menuOpen, HOVER_CARD_OPEN_DELAY_MS, HOVER_CARD_CLOSE_MS)
    const { openStepMenu } = useActions(tileCanvasLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    useRaisedNode(ref, hover.mounted)
    const marker = actionValidationErrorsById[action.id]?.valid === false ? <TileAttentionMarker /> : undefined
    const face = (
        <div
            className={cn(
                'relative rounded-xl',
                (selected || menuOpen) && 'ring-2 ring-[var(--color-accent)] ring-offset-4'
            )}
        >
            <TileFace tile={tile} count={count} marker={marker} />
            {hover.mounted && (
                <TileHoverCard
                    open={hover.open}
                    action={action}
                    tile={tile}
                    count={count}
                    marker={marker}
                    hint="Click to open the step"
                />
            )}
        </div>
    )

    return (
        <div
            ref={ref}
            className="flex cursor-pointer items-start gap-3 text-primary"
            title={hover.mounted ? undefined : action.name}
            onMouseMove={hover.onMouseMove}
            onMouseLeave={hover.onMouseLeave}
            data-attr={interactive ? 'workflow-tile-step' : undefined}
            onContextMenu={
                interactive && hasStepMenu(action)
                    ? (event) => {
                          event.preventDefault()
                          openStepMenu(action.id)
                      }
                    : undefined
            }
        >
            {interactive ? <TileStepMenu action={action}>{face}</TileStepMenu> : face}
            <TileCaption facts={tile.facts} name={tile.customName} />
        </div>
    )
}
