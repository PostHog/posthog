import './AdventFlowStage.scss'

import { useActions, useValues } from 'kea'
import { CSSProperties, Fragment, MouseEvent, ReactNode, useCallback, useEffect, useMemo } from 'react'

import { cn } from 'lib/utils/css-classes'

import { adventCalendarLogic } from '../adventCalendarLogic'
import { ADVENT_LAST_DAY } from '../adventContent'
import { AdventCardFace, AdventDoorCard } from '../AdventDoorCard'
import { AdventDoor } from '../adventGraph'
import { adventPaletteStyle } from '../adventPalette'
import { useAdventCard } from '../useAdventCard'
import { useAdventEscape } from '../useAdventEscape'
import { useAdventStageSize } from '../useAdventStageSize'
import { AdventFlowEdges } from './AdventFlowEdges'
import { AdventFlowFit, adventFlowOrientation } from './adventFlowFit'
import {
    ADVENT_FLOW_DOOR,
    AdventFlowEdge,
    AdventFlowLayout,
    adventFlowLayout,
    AdventFlowNode,
} from './adventFlowLayout'
import { AdventFlowStep, AdventFlowStepProps } from './AdventFlowStep'
import { useAdventCardFocus } from './useAdventCardFocus'
import { useAdventFlowHover } from './useAdventFlowHover'
import { AdventFlowViewport, useAdventFlowViewport } from './useAdventFlowViewport'
import { useAdventFlowWake } from './useAdventFlowWake'

const FACE_DOOR_SIZE = 56
const DOT_GAP = 36
const OPENING_MS = 2400

export interface AdventFlowStageProps {
    // Draws the last door in place of the peek door. While it opens, the stage holds the card back until the
    // drawn door calls `onOpened`, so that door sets the length of its own opening.
    renderLastDoor?: (step: AdventFlowStepProps) => ReactNode
    isEdgeEmphasized?: (edge: AdventFlowEdge) => boolean
}

const noEmphasis = (): boolean => false

function faceOf(node: AdventFlowNode, zoom: number, rectOnStage: AdventFlowViewport['rectOnStage']): AdventCardFace {
    const { x, y, width } = rectOnStage(node.tile)
    return { left: x, top: y, size: width, zoom: (zoom * ADVENT_FLOW_DOOR.width) / FACE_DOOR_SIZE }
}

function cardDoorOf(node: AdventFlowNode, face: AdventCardFace, stageHeight: number, isRows: boolean): AdventDoor {
    const row = isRows ? node.row : face.top > stageHeight / 2 ? 2 : 0
    return { ...(node.door as AdventDoor), row }
}

function gridOf({ zoom, box }: AdventFlowFit): CSSProperties {
    return {
        '--advent-flow-dot-gap': `${DOT_GAP * zoom}px`,
        '--advent-flow-dot-x': `${box.left}px`,
        '--advent-flow-dot-y': `${box.top}px`,
    } as CSSProperties
}

// The peek door's opening runs in CSS for this long, then the card shows. A door drawn by `renderLastDoor`
// ends its own opening through `onOpened`.
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

const nodeOfDoor = (layout: AdventFlowLayout, doorId: string | null): AdventFlowNode | null =>
    layout.nodes.find((node) => !!node.door && node.door.id === doorId) ?? null

export function AdventFlowStage({ renderLastDoor, isEdgeEmphasized = noEmphasis }: AdventFlowStageProps): JSX.Element {
    const { graph, today, selectedDoorId, revealingDoor, pollShares } = useValues(adventCalendarLogic)
    const { activateDoor, answerDoor, clearSelection, finishReveal, clickTip } = useActions(adventCalendarLogic)
    const { ref, stage } = useAdventStageSize()
    const orientation = adventFlowOrientation(stage)
    const layout = useMemo(() => adventFlowLayout(graph, pollShares, orientation), [graph, pollShares, orientation])
    const { fit, track, rectOnStage } = useAdventFlowViewport(stage, layout, today)
    const { zoom, box } = fit
    const isRows = orientation === 'rows'
    useOpening(revealingDoor, !!renderLastDoor, finishReveal)

    const card = useAdventCard(selectedDoorId, !revealingDoor)
    const cardNode = nodeOfDoor(layout, card.doorId)
    const { clearHover } = card
    const dismiss = useCallback((): void => {
        clearSelection()
        clearHover()
    }, [clearSelection, clearHover])
    useAdventEscape(!!revealingDoor, finishReveal, dismiss)
    useAdventCardFocus(ref, card.isPinned, cardNode)
    useAdventFlowWake(ref)
    const hover = useAdventFlowHover(card)

    const onTrackClick = (event: MouseEvent): void => {
        if (!(event.target as Element).closest('button')) {
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
    const face = cardNode ? faceOf(cardNode, zoom, rectOnStage) : null

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
                        onScroll={!isRows && cardNode ? dismiss : undefined}
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
                    {cardNode && face && (
                        <AdventDoorCard
                            key={cardNode.id}
                            door={cardDoorOf(cardNode, face, stage.height, isRows)}
                            shares={pollShares[cardNode.door?.day ?? 0]}
                            face={face}
                            stage={stage}
                            isOpen={card.isOpen}
                            isPinned={card.isPinned}
                            onPin={activateDoor}
                            onAnswer={answerDoor}
                            onTipClick={clickTip}
                            onClose={dismiss}
                            onMouseEnter={card.onEnterCard}
                            onMouseLeave={card.onLeaveDoor}
                        />
                    )}
                </>
            )}
        </div>
    )
}
