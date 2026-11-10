import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import { StepImportNotesBadge } from '../../../import/StepImportNotesBadge'
import { canMoveStep } from '../../hogFlowEditorLogic'
import type { HogFlow, HogFlowAction } from '../../types'
import { tileCanvasLogic } from './tileCanvasLogic'
import { hasStepMenu, MOVING_STEP_ATTR, STEP_DRAG_DATA_TYPE } from './tileCanvasModel'
import { TileCaption } from './TileCaption'
import { TileFace } from './TileFace'
import { HOVER_CARD_CLOSE_MS, TileHoverCard } from './TileHoverCard'
import { TileStepMenu } from './TileStepMenu'
import { useHoverIntent } from './useHoverIntent'
import { useRaisedNode } from './useRaisedNode'
import { useTileStep } from './useTileStep'

const HOVER_OPEN_DELAY_MS = 260

function movingStepAttrs(isMoving: boolean): Record<string, string> {
    return isMoving ? { [MOVING_STEP_ATTR]: '' } : {}
}

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
    const { movingNodeId } = useValues(tileCanvasLogic)
    const hover = useHoverIntent(
        interactive && !selected && !menuOpen && !movingNodeId,
        HOVER_OPEN_DELAY_MS,
        HOVER_CARD_CLOSE_MS
    )
    const { openStepMenu, startDraggingStep, endDraggingStep } = useActions(tileCanvasLogic)
    const draggable = interactive && canMoveStep(workflow, action.id)
    useRaisedNode(ref, hover.mounted)
    const face = (
        <div
            className={cn(
                'relative rounded-xl',
                (selected || menuOpen) && 'ring-2 ring-[var(--color-accent)] ring-offset-4'
            )}
        >
            <TileFace tile={tile} count={count} />
            {interactive && workflow.id ? <StepImportNotesBadge workflowId={workflow.id} stepId={action.id} /> : null}
            {hover.mounted && (
                <TileHoverCard open={hover.open} action={action} tile={tile} count={count} workflowId={workflow.id} />
            )}
        </div>
    )

    return (
        <div
            ref={ref}
            className={cn(
                'flex cursor-pointer items-start gap-3 text-primary transition-opacity',
                draggable && 'nopan',
                movingNodeId === action.id && 'opacity-40'
            )}
            title={hover.mounted ? undefined : action.name}
            onMouseMove={hover.onMouseMove}
            onMouseLeave={hover.onMouseLeave}
            data-attr={interactive ? 'workflow-tile-step' : undefined}
            {...movingStepAttrs(movingNodeId === action.id)}
            draggable={draggable}
            onDragStart={
                draggable
                    ? (event) => {
                          event.dataTransfer.effectAllowed = 'move'
                          event.dataTransfer.setData(STEP_DRAG_DATA_TYPE, action.id)
                          startDraggingStep(action.id)
                      }
                    : undefined
            }
            onDragEnd={draggable ? (event) => endDraggingStep(event.dataTransfer.dropEffect) : undefined}
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
