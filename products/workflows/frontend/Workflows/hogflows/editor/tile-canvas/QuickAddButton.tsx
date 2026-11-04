import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconPlus } from '@posthog/icons'

import { Popover } from 'lib/lemon-ui/Popover'
import { cn } from 'lib/utils/css-classes'

import { getEdgeId } from '../../edgeId'
import type { HogFlowEdge } from '../../types'
import { StepPalette } from './StepPalette'
import { tileCanvasLogic } from './tileCanvasLogic'
import { Point } from './tileCanvasModel'

/** Marks the + button, so a drop can tell a release on it from one snapped to it. */
export const QUICK_ADD_ATTR = 'workflow-tile-quick-add'

function buttonLook(isDropTarget: boolean, isActive: boolean, revealed: boolean): string {
    if (isDropTarget) {
        return 'scale-[1.6] border-[var(--color-accent)] bg-[var(--color-accent)] text-white shadow-md'
    }
    if (isActive) {
        return 'scale-125 border-[var(--color-accent)] text-[var(--color-accent)] shadow'
    }
    return revealed ? 'opacity-100' : 'opacity-0 hover:opacity-100 focus-visible:opacity-100'
}

export function QuickAddButton({
    edge,
    at,
    revealed = false,
    isDropTarget = false,
}: {
    edge: HogFlowEdge
    at: Point
    /** The pointer is on the arrow, so its button shows. */
    revealed?: boolean
    /** A dragged step is nearest to this button, so a drop lands here. */
    isDropTarget?: boolean
}): JSX.Element | null {
    const buttonRef = useRef<HTMLButtonElement>(null)
    const { quickAddEdgeKey, isPlacing, paletteSections, placementLabel, placeableEdgeKeys, isDraggingNewStep } =
        useValues(tileCanvasLogic)
    const { openQuickAdd, closeQuickAdd, addStepAt, placeAt, startDraggingNewStep, endDraggingNewStep } =
        useActions(tileCanvasLogic)
    const key = getEdgeId(edge)
    const isOpen = quickAddEdgeKey === key
    const label = isPlacing ? 'Place the step here' : 'Add a step here'

    if (placeableEdgeKeys && !placeableEdgeKeys.has(key)) {
        return null
    }

    return (
        <div
            className={cn('nodrag nopan pointer-events-auto absolute', isDropTarget && 'z-10')}
            style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
        >
            <Popover
                visible={isOpen}
                className={isDraggingNewStep ? 'invisible' : undefined}
                placement="right-start"
                // Side placements only. The popover puts its gap on the side that faces the +, so a top or bottom
                // placement changes the window's size, and near an edge flip then swaps placements on every frame.
                fallbackPlacements={['left-start', 'left', 'left-end']}
                overlay={
                    <StepPalette
                        sections={paletteSections}
                        placeholder="Search steps"
                        trigger={buttonRef}
                        onSelectStep={(step) => addStepAt(step, edge)}
                        onDragStep={startDraggingNewStep}
                        onDragEnd={endDraggingNewStep}
                        onClose={closeQuickAdd}
                    />
                }
            >
                <button
                    type="button"
                    ref={buttonRef}
                    aria-label={label}
                    title={label}
                    data-attr={QUICK_ADD_ATTR}
                    onClick={() => (isPlacing ? placeAt(edge) : isOpen ? closeQuickAdd() : openQuickAdd(key))}
                    className={cn(
                        'flex size-5 cursor-pointer items-center justify-center rounded-full border bg-surface-primary text-secondary transition-all duration-200 ease-out hover:scale-125 hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] motion-reduce:transition-none',
                        buttonLook(isDropTarget, isPlacing || isOpen, revealed)
                    )}
                >
                    <IconPlus className="text-xs" />
                </button>
            </Popover>
            {isPlacing && placementLabel && (
                <div
                    aria-hidden="true"
                    className={cn(
                        'pointer-events-none absolute left-full top-1/2 ml-3 whitespace-nowrap rounded-full border border-[var(--color-accent)] bg-surface-primary px-2 py-0.5 text-xs font-semibold text-[var(--color-accent)] shadow transition-all duration-200 ease-out motion-reduce:transition-none',
                        isDropTarget
                            ? '-translate-y-1/2 opacity-100'
                            : '-translate-x-1 -translate-y-1/2 scale-90 opacity-0'
                    )}
                >
                    {placementLabel}
                </div>
            )}
        </div>
    )
}
