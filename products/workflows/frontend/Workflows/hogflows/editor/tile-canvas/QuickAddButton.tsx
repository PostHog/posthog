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
}): JSX.Element {
    const buttonRef = useRef<HTMLButtonElement>(null)
    const { quickAddEdgeKey, isPlacing, paletteSections, nodeToBeAdded } = useValues(tileCanvasLogic)
    const { openQuickAdd, closeQuickAdd, addStepAt, placeAt } = useActions(tileCanvasLogic)
    const key = getEdgeId(edge)
    const isOpen = quickAddEdgeKey === key
    const stepName = nodeToBeAdded && 'data' in nodeToBeAdded ? nodeToBeAdded.data.name : nodeToBeAdded?.name

    return (
        <div
            className={cn('nodrag nopan pointer-events-auto absolute', isDropTarget && 'z-10')}
            style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
        >
            <Popover
                visible={isOpen}
                placement="right-start"
                fallbackPlacements={['left-start', 'left', 'left-end', 'bottom-start', 'top-start']}
                overlay={
                    <StepPalette
                        sections={paletteSections}
                        placeholder="Search steps"
                        trigger={buttonRef}
                        onSelectStep={(step) => addStepAt(step, edge)}
                        onClose={closeQuickAdd}
                    />
                }
            >
                <button
                    type="button"
                    ref={buttonRef}
                    aria-label={isPlacing ? 'Place the step here' : 'Add a step here'}
                    title={isPlacing ? 'Place the step here' : 'Add a step here'}
                    data-attr="workflow-tile-quick-add"
                    onClick={() => (isPlacing ? placeAt(edge) : isOpen ? closeQuickAdd() : openQuickAdd(key))}
                    className={cn(
                        'flex size-5 cursor-pointer items-center justify-center rounded-full border bg-surface-primary text-secondary transition-all duration-200 ease-out hover:scale-125 hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] motion-reduce:transition-none',
                        isDropTarget
                            ? 'scale-[1.6] border-[var(--color-accent)] bg-[var(--color-accent)] text-white shadow-md'
                            : isPlacing || isOpen
                              ? 'scale-125 border-[var(--color-accent)] text-[var(--color-accent)] shadow'
                              : revealed
                                ? 'opacity-100'
                                : 'opacity-0 hover:opacity-100 focus-visible:opacity-100'
                    )}
                >
                    <IconPlus className="text-xs" />
                </button>
            </Popover>
            {isPlacing && stepName && (
                <div
                    aria-hidden="true"
                    className={cn(
                        'pointer-events-none absolute left-full top-1/2 ml-3 whitespace-nowrap rounded-full border border-[var(--color-accent)] bg-surface-primary px-2 py-0.5 text-xs font-semibold text-[var(--color-accent)] shadow transition-all duration-200 ease-out motion-reduce:transition-none',
                        isDropTarget
                            ? '-translate-y-1/2 opacity-100'
                            : '-translate-x-1 -translate-y-1/2 scale-90 opacity-0'
                    )}
                >
                    Add {stepName} here
                </div>
            )}
        </div>
    )
}
