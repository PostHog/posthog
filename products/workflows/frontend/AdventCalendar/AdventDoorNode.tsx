import './AdventCalendar.scss'

import { Handle, Node, NodeProps, Position } from '@xyflow/react'

import { IconLock } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

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

function doorLabel(door: AdventDoor, isToday: boolean): string {
    if (door.question) {
        return `${door.question.topic}?`
    }
    if (door.status === 'locked') {
        return `Dec ${door.day}`
    }
    return isToday ? 'Today' : 'Ready'
}

export function AdventDoorNode({ data }: NodeProps<AdventDoorNodeType>): JSX.Element {
    const { door, isSelected, isToday, isOpening } = data
    const isClosed = door.status !== 'open' && !isOpening
    const color = adventDoorColor(door)

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
                        aria-label={`Door ${door.day}, ${door.status}`}
                        className={cn(
                            'AdventDoor relative flex size-full items-center justify-center rounded-xl border-2 bg-surface-primary p-0 text-2xl font-bold shadow-md',
                            'cursor-pointer',
                            isSelected && 'outline outline-2 outline-offset-4 outline-accent'
                        )}
                        style={{
                            borderColor: color,
                            color: door.status === 'ready' ? color : 'var(--color-text-tertiary)',
                        }}
                    >
                        <span>{door.day}</span>
                        {door.status === 'locked' && <IconLock className="absolute right-1 top-1 text-sm" />}
                    </button>
                    <span className="pointer-events-none absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap rounded bg-surface-primary px-1 text-[11px] leading-4 text-secondary">
                        {doorLabel(door, isToday)}
                    </span>
                </>
            )}
        </div>
    )
}
