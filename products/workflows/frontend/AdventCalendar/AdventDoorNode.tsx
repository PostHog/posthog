import './AdventCalendar.scss'

import { Handle, Node, NodeProps, Position } from '@xyflow/react'

import { IconLock } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { ADVENT_LAST_DAY } from './adventContent'
import { AdventDoor, adventDoorColor, AdventSide } from './adventGraph'

export type AdventDoorNodeType = Node<
    { door: AdventDoor; isSelected: boolean; isToday: boolean; isOpening: boolean },
    'door'
>

const SIDES: Record<AdventSide, Position> = {
    left: Position.Left,
    right: Position.Right,
    top: Position.Top,
    bottom: Position.Bottom,
}

function doorLabel(door: AdventDoor, isToday: boolean): string | null {
    if (door.question) {
        return `${door.question.topic}?`
    }
    if (door.status === 'locked') {
        return null
    }
    return isToday ? 'Today' : 'Ready'
}

function doorName(door: AdventDoor): string {
    return door.lockReason === 'date'
        ? `Door ${door.day}, opens December ${door.day}`
        : `Door ${door.day}, ${door.status}`
}

function doorColors(door: AdventDoor): { borderColor: string; color: string } {
    const color = adventDoorColor(door)
    return { borderColor: color, color: door.status === 'ready' ? color : 'var(--color-text-tertiary)' }
}

export function AdventDoorNode({ data }: NodeProps<AdventDoorNodeType>): JSX.Element {
    const { door, isSelected, isToday, isOpening } = data
    const isClosed = door.status !== 'open' && !isOpening
    const isExit = door.day === ADVENT_LAST_DAY
    const label = doorLabel(door, isToday)

    return (
        <div className={cn('relative size-14', !isClosed && 'pointer-events-none')}>
            {(Object.keys(SIDES) as AdventSide[]).map((side) => (
                <span key={side}>
                    <Handle
                        id={`in-${side}`}
                        type="target"
                        position={SIDES[side]}
                        isConnectable={false}
                        className="!pointer-events-none !opacity-0"
                    />
                    <Handle
                        id={`out-${side}`}
                        type="source"
                        position={SIDES[side]}
                        isConnectable={false}
                        className="!pointer-events-none !opacity-0"
                    />
                </span>
            ))}
            {isClosed && (
                <>
                    <button
                        type="button"
                        data-attr={`advent-door-${door.day}`}
                        aria-label={doorName(door)}
                        className={cn(
                            'AdventDoor relative flex size-full items-center justify-center border-2 bg-surface-primary p-0 text-2xl font-bold shadow-md',
                            isExit ? 'rounded-l-xl rounded-r-[1.75rem]' : 'rounded-xl',
                            'cursor-pointer',
                            isSelected && 'outline outline-2 outline-offset-4 outline-accent'
                        )}
                        style={doorColors(door)}
                    >
                        <span>{door.day}</span>
                        {door.status === 'locked' && (
                            <IconLock className={cn('absolute top-1 text-sm', isExit ? 'left-1' : 'right-1')} />
                        )}
                    </button>
                    {label && (
                        <span className="pointer-events-none absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap rounded bg-surface-primary px-1 text-[11px] leading-4 text-secondary">
                            {label}
                        </span>
                    )}
                </>
            )}
        </div>
    )
}
