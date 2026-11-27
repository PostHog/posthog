import './AdventCalendar.scss'

import { CSSProperties } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ADVENT_CARD_EDGE_GAP, ADVENT_CARD_INSET, adventCardPlacement } from './adventCardPlacement'
import { ADVENT_TIPS } from './adventContent'
import { AdventDoorAnswer } from './AdventDoorAnswer'
import { AdventDoorFace } from './AdventDoorFace'
import { AdventDoor, adventDoorColor, adventWeekday } from './adventGraph'
import { AdventTipCard } from './AdventTipCard'
import { ADVENT_CARD_CLOSE_MS } from './useAdventCard'

const OPEN_CLIP = 'inset(-2px round 16px)'
const OPEN_MS = 480

export interface AdventCardFace {
    left: number
    top: number
    size: number
    zoom: number
}

export interface AdventDoorCardProps {
    door: AdventDoor
    shares?: Record<string, number>
    face: AdventCardFace
    stage: { width: number; height: number }
    isOpen: boolean
    isPinned: boolean
    onPin: (doorId: string) => void
    onAnswer: (doorId: string, optionId: string) => void
    onTipClick: (day: number) => void
    onClose: () => void
    onMouseEnter: () => void
    onMouseLeave: () => void
}

function closedClip(faceSize: number, faceInset: number, isLeftward: boolean): string {
    const [top, bottom] = [`${ADVENT_CARD_INSET}px`, `calc(100% - ${ADVENT_CARD_INSET + faceSize}px)`]
    const [right, left] = isLeftward
        ? [`${faceInset}px`, `calc(100% - ${faceInset + faceSize}px)`]
        : [`calc(100% - ${faceInset + faceSize}px)`, `${faceInset}px`]
    return `inset(${top} ${right} ${bottom} ${left} round 12px)`
}

function cardLayout(
    door: AdventDoor,
    face: AdventCardFace,
    stage: AdventDoorCardProps['stage'],
    isOpen: boolean
): { style: CSSProperties; faceShift: CSSProperties; isLeftward: boolean } {
    const { isLeftward, left, width, faceInset } = adventCardPlacement(face, stage.width, door.row)
    const isUpward = door.row === 2
    const faceTop = face.top - ADVENT_CARD_INSET
    const faceBottom = face.top + face.size + ADVENT_CARD_INSET
    const vertical: CSSProperties = isUpward
        ? { bottom: stage.height - faceBottom, maxHeight: faceBottom - ADVENT_CARD_EDGE_GAP }
        : { top: faceTop, maxHeight: stage.height - faceTop - ADVENT_CARD_EDGE_GAP }
    const style: CSSProperties = {
        width,
        left,
        ...vertical,
        borderColor: adventDoorColor(door),
        clipPath: isOpen ? OPEN_CLIP : closedClip(face.size, faceInset, isLeftward),
        transitionDuration: `${isOpen ? OPEN_MS : ADVENT_CARD_CLOSE_MS}ms`,
    }
    const shift = faceInset - ADVENT_CARD_INSET
    const faceShift: CSSProperties = isLeftward ? { marginRight: shift } : { marginLeft: shift }
    return { style, faceShift, isLeftward }
}

function headline(door: AdventDoor): { title: string; detail: string | null } {
    if (door.status === 'open') {
        return { title: door.reward?.name ?? `Door ${door.day}`, detail: door.reward?.line ?? null }
    }
    if (door.status === 'locked') {
        return {
            title: door.question ? door.question.topic : 'Locked',
            detail: door.lockReason === 'date' ? `Opens December ${door.day}.` : 'Open the earlier doors first.',
        }
    }
    return door.question
        ? { title: door.question.topic, detail: 'Pick a side to open this door.' }
        : { title: 'Ready to open', detail: 'Select the door to see who is behind it.' }
}

export function AdventDoorCard({
    door,
    shares,
    face,
    stage,
    isOpen,
    isPinned,
    onPin,
    onAnswer,
    onTipClick,
    onClose,
    onMouseEnter,
    onMouseLeave,
}: AdventDoorCardProps): JSX.Element {
    const { title, detail } = headline(door)
    const { style, faceShift, isLeftward } = cardLayout(door, face, stage, isOpen)

    return (
        <div
            className={cn('AdventCard', isOpen && 'AdventCard--open')}
            style={style}
            data-attr="advent-door-card"
            data-open={isOpen}
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
        >
            <div className={cn('flex items-start gap-3', isLeftward && 'flex-row-reverse')}>
                <AdventDoorFace
                    door={door}
                    size={face.size}
                    zoom={face.zoom}
                    style={faceShift}
                    onClick={() => onPin(door.id)}
                />
                <div className="AdventCard__fade flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-[11px] text-secondary" translate="no">
                        {adventWeekday(door.day)}
                    </span>
                    <span className="text-sm font-semibold leading-tight">{title}</span>
                    {detail && (
                        <span
                            className={cn(
                                'text-xs leading-snug text-secondary',
                                door.lockReason === 'date' && 'whitespace-nowrap'
                            )}
                        >
                            {detail}
                        </span>
                    )}
                </div>
                {isPinned && (
                    <LemonButton
                        className="AdventCard__fade shrink-0 self-start"
                        size="xsmall"
                        icon={<IconX />}
                        aria-label="Close"
                        data-attr="advent-door-card-close"
                        onClick={onClose}
                    />
                )}
            </div>

            <div className="AdventCard__fade AdventCard__body">
                <AdventDoorAnswer door={door} shares={shares} onAnswer={onAnswer} />
                {door.status === 'open' && (
                    <AdventTipCard tip={ADVENT_TIPS[door.day]} onLinkClick={() => onTipClick(door.day)} />
                )}
            </div>
        </div>
    )
}
