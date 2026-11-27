import './AdventFlowStage.scss'

import { useActions, useValues } from 'kea'
import {
    CSSProperties,
    Fragment,
    MouseEvent,
    ReactNode,
    RefObject,
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
} from 'react'

import { cn } from 'lib/utils/css-classes'

import { adventCalendarLogic } from '../adventCalendarLogic'
import { ADVENT_LAST_DAY } from '../adventContent'
import { AdventCardFace, AdventDoorCard } from '../AdventDoorCard'
import { AdventDoor, adventDayColor } from '../adventGraph'
import { adventPaletteStyle } from '../adventPalette'
import { useAdventCard } from '../useAdventCard'
import { useAdventEscape } from '../useAdventEscape'
import { useAdventStageSize } from '../useAdventStageSize'
import { AdventFlowEdges } from './AdventFlowEdges'
import { AdventFlowFit, adventFlowFit, adventFlowOrientation } from './adventFlowFit'
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

const FACE_DOOR_SIZE = 56
const DOT_GAP = 36

export interface AdventFlowStageProps {
    renderLastDoor?: (step: AdventFlowStepProps) => ReactNode
    isEdgeEmphasized?: (edge: AdventFlowEdge) => boolean
}

const noEmphasis = (): boolean => false

function faceOf(node: AdventFlowNode, { zoom, box }: AdventFlowFit, scrollTop: number): AdventCardFace {
    return {
        left: box.left + node.tile.x * zoom,
        top: box.top + node.tile.y * zoom - scrollTop,
        size: ADVENT_FLOW_DOOR.width * zoom,
        zoom: (zoom * ADVENT_FLOW_DOOR.width) / FACE_DOOR_SIZE,
        tint: node.door ? adventDayColor(node.door.day) : undefined,
    }
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

function useTodayInView(
    layout: AdventFlowLayout,
    today: number,
    zoom: number,
    stageHeight: number
): RefObject<HTMLDivElement> {
    const track = useRef<HTMLDivElement>(null)
    const todayTop = layout.nodes.find((node) => node.door?.day === today)?.tile.y ?? 0
    const isColumn = layout.orientation === 'column'
    useLayoutEffect(() => {
        if (isColumn && track.current) {
            track.current.scrollTop = todayTop * zoom - stageHeight / 2
        }
    }, [isColumn, todayTop, zoom, stageHeight])
    return track
}

const nodeOfDoor = (layout: AdventFlowLayout, doorId: string | null): AdventFlowNode | null =>
    layout.nodes.find((node) => !!node.door && node.door.id === doorId) ?? null

export function AdventFlowStage({ renderLastDoor, isEdgeEmphasized = noEmphasis }: AdventFlowStageProps): JSX.Element {
    const { graph, today, selectedDoorId, revealingDoor, pollShares } = useValues(adventCalendarLogic)
    const { activateDoor, answerDoor, clearSelection, finishReveal, clickTip } = useActions(adventCalendarLogic)
    const { ref, stage } = useAdventStageSize()
    const orientation = adventFlowOrientation(stage)
    const layout = useMemo(() => adventFlowLayout(graph, pollShares, orientation), [graph, pollShares, orientation])
    const fit = adventFlowFit(stage, layout)
    const { zoom, box } = fit
    const isRows = orientation === 'rows'
    const track = useTodayInView(layout, today, zoom, stage.height)

    useEffect(() => {
        if (revealingDoor) {
            finishReveal()
        }
    }, [revealingDoor, finishReveal])

    const card = useAdventCard(selectedDoorId, !revealingDoor)
    const cardNode = nodeOfDoor(layout, card.doorId)
    const { clearHover } = card
    const dismiss = useCallback((): void => {
        clearSelection()
        clearHover()
    }, [clearSelection, clearHover])
    useAdventEscape(!!revealingDoor, finishReveal, dismiss)
    useAdventCardFocus(ref, card.isPinned, cardNode, dismiss)
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
        onActivate: activateDoor,
        onEnter: hover.onEnter,
        onLeave: hover.onLeave,
    })
    const face = cardNode ? faceOf(cardNode, fit, track.current?.scrollTop ?? 0) : null

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
