import './AdventFlowStage.scss'

import { CSSProperties, memo } from 'react'

import { IconCalendar, IconLeave } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { TileBadge } from '../../Workflows/hogflows/editor/tile-canvas/TileBadge'
import { AdventDoor, adventDayColor, adventWeekday } from '../adventGraph'
import { AdventFlowNode, AdventFlowOrientation, AdventFlowRect } from './adventFlowLayout'
import { AdventFlowPeek } from './AdventFlowPeek'

export interface AdventFlowStepProps {
    node: AdventFlowNode
    orientation: AdventFlowOrientation
    today: number
    isSelected: boolean
    isOpening: boolean
    onOpened: () => void
    onActivate: (doorId: string) => void
    onEnter: (doorId: string) => void
    onLeave: () => void
}

interface Caption {
    title: string | null
    detail: string | null
}

function doorCaption(door: AdventDoor, today: number): Caption {
    const topic = door.question ? `${door.question.topic}?` : null
    if (door.status === 'open') {
        return { title: door.reward?.name ?? null, detail: door.answer?.label ?? null }
    }
    if (door.status === 'ready') {
        return { title: topic ?? (door.day === today ? 'Today' : 'Ready to open'), detail: topic && 'Answer to open' }
    }
    return { title: topic, detail: null }
}

function captionOf(node: AdventFlowNode, today: number): Caption {
    if (node.door) {
        return doorCaption(node.door, today)
    }
    return node.kind === 'trigger'
        ? { title: 'Every day in December', detail: 'One door a day' }
        : { title: 'Exit', detail: 'December 25' }
}

function doorName(door: AdventDoor): string {
    if (door.status === 'open') {
        return `Door ${door.day}, open: ${door.reward?.name ?? 'opened'}`
    }
    return door.lockReason === 'date'
        ? `Door ${door.day}, opens December ${door.day}`
        : `Door ${door.day}, ${door.status}`
}

const at = ({ x, y, width, height }: AdventFlowRect): CSSProperties => ({ left: x, top: y, width, height })

const captionId = (node: AdventFlowNode): string => `advent-flow-caption-${node.id}`

function captionAlign(orientation: AdventFlowOrientation, node: AdventFlowNode): string {
    if (orientation === 'column') {
        return 'items-start justify-center text-left'
    }
    return node.lane === 'upper' ? 'items-center justify-end text-center' : 'items-center justify-start text-center'
}

function EndTile({ node, orientation }: Pick<AdventFlowStepProps, 'node' | 'orientation'>): JSX.Element {
    const isExit = node.kind === 'exit'
    return (
        <div
            className={cn(
                'AdventFlowStep__tile AdventFlowStep__end absolute flex items-center justify-center rounded-xl border-2',
                `AdventFlowStep__end--${orientation}`,
                isExit ? 'AdventFlowStep__end--exit' : 'AdventFlowStep__end--trigger'
            )}
            style={at(node.tile)}
            aria-describedby={captionId(node)}
        >
            {isExit ? <IconLeave /> : <IconCalendar />}
            {!isExit && (
                <TileBadge placement="setting" color="var(--color-accent)">
                    Daily
                </TileBadge>
            )}
        </div>
    )
}

function doorTileClass(door: AdventDoor, today: number, isSelected: boolean): string {
    return cn(
        'AdventFlowStep__tile absolute rounded-xl p-0',
        door.status === 'open'
            ? 'AdventFlowStep__tile--open'
            : 'flex items-center justify-center border-2 text-2xl font-bold',
        door.status === 'ready' && door.day === today && 'AdventFlowStep__tile--today',
        isSelected && 'outline outline-2 outline-offset-4 outline-accent'
    )
}

const doorBadge = (door: AdventDoor): string => (door.question ? '2 paths' : adventWeekday(door.day).slice(0, 3))

function ClosedDoor({ door }: { door: AdventDoor }): JSX.Element {
    return (
        <>
            {door.day}
            <TileBadge placement="setting" color={adventDayColor(door.day)}>
                {doorBadge(door)}
            </TileBadge>
        </>
    )
}

// An opening door keeps its button, so a keyboard user who opened it keeps focus on it.
function DoorTile({
    node,
    today,
    isSelected,
    isOpening,
    onActivate,
    onEnter,
    onLeave,
}: AdventFlowStepProps): JSX.Element {
    const door = node.door as AdventDoor
    const color = adventDayColor(door.day)
    const isOpen = door.status === 'open'
    const hover = isOpen ? {} : { onMouseEnter: () => onEnter(door.id), onMouseLeave: onLeave }
    return (
        <button
            type="button"
            data-attr={isOpen ? `advent-hog-${door.day}` : `advent-door-${door.day}`}
            aria-label={doorName(door)}
            aria-describedby={captionId(node)}
            className={doorTileClass(door, today, isSelected)}
            style={{ ...at(node.tile), borderColor: color, color }}
            onClick={() => onActivate(door.id)}
            {...hover}
        >
            {isOpen ? <AdventFlowPeek door={door} isOpening={isOpening} /> : <ClosedDoor door={door} />}
        </button>
    )
}

export const AdventFlowStep = memo(function AdventFlowStep(props: AdventFlowStepProps): JSX.Element {
    const { node, orientation, today } = props
    const { title, detail } = captionOf(node, today)
    return (
        <>
            {node.door ? <DoorTile {...props} /> : <EndTile node={node} orientation={orientation} />}
            <span
                id={captionId(node)}
                className={cn(
                    'AdventFlowStep__caption pointer-events-none absolute flex flex-col leading-tight',
                    captionAlign(orientation, node)
                )}
                style={at(node.caption)}
            >
                {title && (
                    <span className="line-clamp-2 max-w-full text-[12px] font-semibold text-primary">{title}</span>
                )}
                {detail && <span className="line-clamp-2 max-w-full text-[11px] text-secondary">{detail}</span>}
            </span>
        </>
    )
})
