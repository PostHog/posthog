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
}: {
    edge: HogFlowEdge
    at: Point
    /** The pointer is on the arrow, so its button shows. */
    revealed?: boolean
}): JSX.Element {
    const buttonRef = useRef<HTMLButtonElement>(null)
    const { quickAddEdgeKey, isPlacing, paletteSections } = useValues(tileCanvasLogic)
    const { openQuickAdd, closeQuickAdd, addStepAt, placeAt, onDrop } = useActions(tileCanvasLogic)
    const key = getEdgeId(edge)
    const isOpen = quickAddEdgeKey === key

    return (
        <div
            className="nodrag nopan pointer-events-auto absolute"
            style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
                event.preventDefault()
                onDrop(undefined, edge)
            }}
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
                        'flex size-5 cursor-pointer items-center justify-center rounded-full border bg-surface-primary text-secondary transition-all hover:scale-125 hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] motion-reduce:transition-none',
                        isPlacing || isOpen
                            ? 'scale-125 border-[var(--color-accent)] text-[var(--color-accent)] shadow'
                            : revealed
                              ? 'opacity-100'
                              : 'opacity-0 hover:opacity-100 focus-visible:opacity-100'
                    )}
                >
                    <IconPlus className="text-xs" />
                </button>
            </Popover>
        </div>
    )
}
