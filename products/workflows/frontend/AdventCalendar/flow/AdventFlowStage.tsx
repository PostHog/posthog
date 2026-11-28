import './AdventFlowStage.scss'

import { useActions, useValues } from 'kea'
import { CSSProperties, Fragment, MouseEvent, ReactNode, useCallback, useEffect, useMemo } from 'react'

import { cn } from 'lib/utils/css-classes'

import { adventCalendarLogic } from '../adventCalendarLogic'
import { ADVENT_LAST_DAY } from '../adventContent'
import { AdventDoor } from '../adventGraph'
import { adventPaletteStyle } from '../adventPalette'
import { useAdventEscape } from '../useAdventEscape'
import { useAdventStageSize } from '../useAdventStageSize'
import { AdventFlowCard } from './AdventFlowCard'
import { AdventFlowEdges } from './AdventFlowEdges'
import { AdventFlowFit, adventFlowOrientation } from './adventFlowFit'
import { AdventFlowEdge, adventFlowLayout, AdventFlowNode } from './adventFlowLayout'
import { AdventFlowStep, AdventFlowStepProps } from './AdventFlowStep'
import { useAdventFlowHover } from './useAdventFlowHover'
import { useAdventFlowViewport } from './useAdventFlowViewport'
import { useAdventFlowWake } from './useAdventFlowWake'

const DOT_GAP = 36
const OPENING_MS = 2400

export interface AdventFlowStageProps {
    // Draws the last door in place of the peek door. While it opens, the stage holds the card back until the
    // drawn door calls `onOpened`, so that door sets the length of its own opening.
    renderLastDoor?: (step: AdventFlowStepProps) => ReactNode
    isEdgeEmphasized?: (edge: AdventFlowEdge) => boolean
}

const noEmphasis = (): boolean => false

function gridOf({ zoom, box }: AdventFlowFit): CSSProperties {
    return {
        '--advent-flow-dot-gap': `${DOT_GAP * zoom}px`,
        '--advent-flow-dot-x': `${box.left}px`,
        '--advent-flow-dot-y': `${box.top}px`,
    } as CSSProperties
}

// The peek door's opening runs in CSS for this long, then the card shows.
function useOpening(revealingDoor: AdventDoor | null, drawsLastDoor: boolean, finishReveal: () => void): void {
    const revealingDoorId = revealingDoor?.id ?? null
    const isHandedOff = drawsLastDoor && revealingDoor?.day === ADVENT_LAST_DAY
    useEffect(() => {
        if (!revealingDoorId || isHandedOff) {
            return
        }
        const timer = window.setTimeout(finishReveal, OPENING_MS)
        return () => window.clearTimeout(timer)
    }, [revealingDoorId, isHandedOff, finishReveal])
}

export function AdventFlowStage({ renderLastDoor, isEdgeEmphasized = noEmphasis }: AdventFlowStageProps): JSX.Element {
    const { graph, today, selectedDoorId, revealingDoor, pollShares } = useValues(adventCalendarLogic)
    const { activateDoor, clearSelection, finishReveal } = useActions(adventCalendarLogic)
    const { ref, stage } = useAdventStageSize()
    const orientation = adventFlowOrientation(stage)
    const layout = useMemo(() => adventFlowLayout(graph, pollShares, orientation), [graph, pollShares, orientation])
    const { fit, track, rectOnStage } = useAdventFlowViewport(stage, layout, today)
    const { zoom, box } = fit
    const isRows = orientation === 'rows'
    useOpening(revealingDoor, !!renderLastDoor, finishReveal)

    const hover = useAdventFlowHover()
    const dismiss = useCallback((): void => {
        clearSelection()
        hover.clearHover()
    }, [clearSelection, hover])
    useAdventEscape(!!revealingDoor, finishReveal, dismiss)
    useAdventFlowWake(ref)

    const onTrackClick = (event: MouseEvent): void => {
        if (!(event.target as Element).closest('button')) {
            dismiss()
        }
    }
    // Scrolling the column moves the doors under a card placed for the old scroll, so the card closes.
    const onColumnScroll = (): void => {
        if (hover.card.current?.doorId) {
            dismiss()
        }
    }
    const stepOf = (node: AdventFlowNode): AdventFlowStepProps => ({
        node,
        orientation,
        today,
        isSelected: node.door?.id === selectedDoorId,
        isOpening: !!revealingDoor && node.door?.id === revealingDoor.id,
        onOpened: finishReveal,
        onActivate: activateDoor,
        onEnter: hover.onEnter,
        onLeave: hover.onLeave,
    })

    return (
        <div
            ref={ref}
            className="AdventFlowStage"
            style={{ ...adventPaletteStyle(), ...gridOf(fit) }}
            data-attr="advent-stage"
        >
            {zoom > 0 && (
                <>
                    <div
                        ref={track}
                        className={cn('AdventFlowStage__track', !isRows && 'AdventFlowStage__track--column')}
                        onScroll={isRows ? undefined : onColumnScroll}
                        onClick={onTrackClick}
                    >
                        <div className="relative" style={fit.content}>
                            <div
                                className="AdventFlowStage__canvas"
                                style={{
                                    left: box.left,
                                    top: box.top,
                                    width: layout.width,
                                    height: layout.height,
                                    transform: `scale(${zoom})`,
                                }}
                            >
                                <AdventFlowEdges layout={layout} isEdgeEmphasized={isEdgeEmphasized} />
                                {layout.nodes.map((node) => (
                                    <Fragment key={node.id}>
                                        {renderLastDoor && node.door?.day === ADVENT_LAST_DAY ? (
                                            renderLastDoor(stepOf(node))
                                        ) : (
                                            <AdventFlowStep {...stepOf(node)} />
                                        )}
                                    </Fragment>
                                ))}
                            </div>
                        </div>
                    </div>
                    <AdventFlowCard
                        stageRef={ref}
                        stage={stage}
                        layout={layout}
                        zoom={zoom}
                        isRows={isRows}
                        rectOnStage={rectOnStage}
                        hover={hover}
                        onDismiss={dismiss}
                    />
                </>
            )}
        </div>
    )
}
