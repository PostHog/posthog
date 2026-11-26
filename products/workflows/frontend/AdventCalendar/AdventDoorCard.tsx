import './AdventCalendar.scss'

import { CSSProperties } from 'react'

import { IconLock, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ADVENT_TIPS } from './adventContent'
import { ADVENT_DOOR_SIZE, AdventDoor, adventDoorColor, adventWeekday } from './adventGraph'
import { AdventRewardArt } from './AdventRewardArt'
import { AdventTipCard } from './AdventTipCard'
import { ADVENT_CARD_CLOSE_MS } from './useAdventCard'

const WIDTH = 320
const INSET = 13
const EDGE_GAP = 8
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

function headline(door: AdventDoor): { title: string; detail: string | null } {
    if (door.status === 'open') {
        return { title: door.reward?.name ?? `Door ${door.day}`, detail: door.reward?.line ?? null }
    }
    if (door.status === 'locked') {
        return {
            title: door.question ? door.question.topic : 'Locked',
            detail:
                door.lockReason === 'date'
                    ? `Opens on ${adventWeekday(door.day)}, December ${door.day}.`
                    : 'Open the earlier doors first.',
        }
    }
    return door.question
        ? { title: door.question.topic, detail: 'Pick a side to open this door.' }
        : { title: 'Ready to open', detail: 'Select the door to see who is behind it.' }
}

export function AdventDoorCard({
    door,
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
    const isHog = door.status === 'open'
    const color = adventDoorColor(door)
    const { title, detail } = headline(door)

    const hasRoomRight = face.left - INSET + WIDTH <= stage.width - EDGE_GAP
    const hasRoomLeft = face.left + face.size + INSET - WIDTH >= EDGE_GAP
    const isLeftward = door.row === 1 ? !hasRoomRight && hasRoomLeft : hasRoomLeft || !hasRoomRight
    const isUpward = door.row === 2
    const far = `calc(100% - ${INSET + face.size}px)`
    const near = `${INSET}px`
    const closedClip = `inset(${isUpward ? far : near} ${isLeftward ? near : far} ${isUpward ? near : far} ${isLeftward ? far : near} round 12px)`

    const style: CSSProperties = {
        width: WIDTH,
        maxHeight: isUpward ? face.top + face.size + INSET - EDGE_GAP : stage.height - (face.top - INSET) - EDGE_GAP,
        ...(isLeftward ? { right: stage.width - (face.left + face.size + INSET) } : { left: face.left - INSET }),
        ...(isUpward ? { bottom: stage.height - (face.top + face.size + INSET) } : { top: face.top - INSET }),
        borderColor: color,
        clipPath: isOpen ? OPEN_CLIP : closedClip,
        transitionDuration: `${isOpen ? OPEN_MS : ADVENT_CARD_CLOSE_MS}ms`,
    }

    return (
        <div
            className={cn('AdventCard', isUpward && 'AdventCard--upward', isOpen && 'AdventCard--open')}
            style={style}
            data-attr="advent-door-card"
            data-open={isOpen}
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
        >
            <div className={cn('flex gap-3', isLeftward && 'flex-row-reverse', isUpward ? 'items-end' : 'items-start')}>
                <button
                    type="button"
                    className="AdventCard__face"
                    style={{ width: face.size, height: face.size }}
                    aria-label={`Door ${door.day}`}
                    onClick={() => onPin(door.id)}
                >
                    {isHog && door.reward ? (
                        <AdventRewardArt reward={door.reward} className="size-full" />
                    ) : (
                        <span
                            className="AdventCard__door"
                            style={{
                                width: ADVENT_DOOR_SIZE,
                                height: ADVENT_DOOR_SIZE,
                                transform: `scale(${face.zoom})`,
                                borderColor: color,
                                color: door.status === 'ready' ? color : 'var(--color-text-tertiary)',
                            }}
                        >
                            {door.day}
                            {door.status === 'locked' && <IconLock className="absolute right-1 top-1 text-sm" />}
                        </span>
                    )}
                </button>
                <div className="AdventCard__fade flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-[11px] text-secondary" translate="no">
                        {`Door ${door.day} · ${adventWeekday(door.day)}`}
                    </span>
                    <span className="text-sm font-semibold leading-tight">{title}</span>
                    {detail && <span className="text-xs leading-snug text-secondary">{detail}</span>}
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
                {door.status === 'ready' && door.question && (
                    <div className="flex flex-col gap-2">
                        <p className="m-0 font-medium">{door.question.prompt}</p>
                        <div className="grid grid-cols-2 gap-2">
                            {door.question.options.map((option) => (
                                <LemonButton
                                    key={option.id}
                                    type="secondary"
                                    fullWidth
                                    center
                                    data-attr="advent-door-answer"
                                    onClick={() => onAnswer(door.id, option.id)}
                                >
                                    {option.label}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                )}
                {isHog && door.question && door.answer && (
                    <div className="flex flex-col gap-0.5 rounded border border-primary bg-surface-secondary p-2 text-xs">
                        <span className="text-secondary">{door.question.prompt}</span>
                        <span>
                            <span className="text-secondary">Your pick:&nbsp;</span>
                            <span className="font-semibold">{door.answer.label}</span>
                        </span>
                        <span>{door.answer.reply}</span>
                    </div>
                )}
                {isHog && <AdventTipCard tip={ADVENT_TIPS[door.day]} onLinkClick={() => onTipClick(door.day)} />}
                {!isPinned && door.status !== 'ready' && (
                    <span className="text-[11px] text-secondary">Click to keep this open</span>
                )}
            </div>
        </div>
    )
}
