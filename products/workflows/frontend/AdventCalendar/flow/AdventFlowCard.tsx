import { useActions, useValues } from 'kea'
import { ReactNode, RefObject } from 'react'

import { adventCalendarLogic } from '../adventCalendarLogic'
import { AdventCardFace, AdventDoorCard } from '../AdventDoorCard'
import { AdventDoor, adventDayColor } from '../adventGraph'
import { useAdventCard } from '../useAdventCard'
import { ADVENT_FLOW_DOOR, AdventFlowLayout, AdventFlowNode } from './adventFlowLayout'
import { useAdventCardFocus } from './useAdventCardFocus'
import { AdventFlowHover } from './useAdventFlowHover'
import { AdventFlowViewport } from './useAdventFlowViewport'

const FACE_DOOR_SIZE = 56

export interface AdventFlowCardProps {
    stageRef: RefObject<HTMLElement>
    stage: { width: number; height: number }
    layout: AdventFlowLayout
    zoom: number
    isRows: boolean
    rectOnStage: AdventFlowViewport['rectOnStage']
    hover: AdventFlowHover
    onDismiss: () => void
}

function faceOf(node: AdventFlowNode, zoom: number, rectOnStage: AdventFlowViewport['rectOnStage']): AdventCardFace {
    const { x, y, width } = rectOnStage(node.tile)
    return {
        left: x,
        top: y,
        size: width,
        zoom: (zoom * ADVENT_FLOW_DOOR.width) / FACE_DOOR_SIZE,
        tint: node.door ? adventDayColor(node.door.day) : undefined,
    }
}

function cardDoorOf(node: AdventFlowNode, face: AdventCardFace, stageHeight: number, isRows: boolean): AdventDoor {
    const row = isRows ? node.row : face.top > stageHeight / 2 ? 2 : 0
    return { ...(node.door as AdventDoor), row }
}

const nodeOfDoor = (layout: AdventFlowLayout, doorId: string | null): AdventFlowNode | null =>
    layout.nodes.find((node) => !!node.door && node.door.id === doorId) ?? null

export function AdventFlowCard({
    stageRef,
    stage,
    layout,
    zoom,
    isRows,
    rectOnStage,
    hover,
    onDismiss,
}: AdventFlowCardProps): JSX.Element | null {
    const { selectedDoorId, revealingDoor, pollShares } = useValues(adventCalendarLogic)
    const { activateDoor, pinDoor, answerDoor, clickTip } = useActions(adventCalendarLogic)
    const card = useAdventCard(selectedDoorId, !revealingDoor)
    hover.card.current = card
    const cardNode = nodeOfDoor(layout, card.doorId)
    const guards = useAdventCardFocus(stageRef, card.isPinned, cardNode, pinDoor)

    if (!cardNode || revealingDoor) {
        return null
    }
    const face = faceOf(cardNode, zoom, rectOnStage)
    const focusGuard = (onFocus: () => void): ReactNode =>
        card.isPinned && <span tabIndex={0} aria-hidden onFocus={onFocus} />
    return (
        <>
            {focusGuard(guards.onFocusStart)}
            <AdventDoorCard
                key={cardNode.id}
                door={cardDoorOf(cardNode, face, stage.height, isRows)}
                shares={pollShares[cardNode.door?.day ?? 0]}
                face={face}
                stage={stage}
                isOpen={card.isOpen}
                isPinned={card.isPinned}
                isDialog
                isClosing={card.isClosing}
                onPin={activateDoor}
                onAnswer={answerDoor}
                onTipClick={clickTip}
                onClose={onDismiss}
                onMouseEnter={card.onEnterCard}
                onMouseLeave={card.onLeaveDoor}
            />
            {focusGuard(guards.onFocusEnd)}
        </>
    )
}
