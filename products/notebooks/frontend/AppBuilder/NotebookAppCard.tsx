import { CSSProperties, PointerEvent, ReactNode, useRef, useState } from 'react'

import { IconExpand45 } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { clamp } from 'lib/utils/numbers'

import type { NotebookAppBlockApi } from '../generated/api.schemas'

export const MIN_CARD_HEIGHT = 120
export const MAX_CARD_HEIGHT = 1600
const GRID_COLUMNS = 12

type CardSize = Pick<NotebookAppBlockApi, 'width' | 'height'>

export function NotebookAppCard({
    block,
    selected,
    toolbar,
    children,
    onSelect,
    onResize,
    onMove,
}: {
    block: NotebookAppBlockApi
    selected: boolean
    toolbar?: ReactNode
    children: ReactNode
    onSelect?: (id: string) => void
    onResize?: (id: string, size: CardSize) => void
    onMove?: (id: string, beforeId: string) => void
}): JSX.Element {
    const slot = useRef<HTMLDivElement>(null)
    const start = useRef<{ x: number; y: number; height: number; columnStep: number } | null>(null)
    const [preview, setPreview] = useState<CardSize | null>(null)
    const width = block.width ?? GRID_COLUMNS
    const size = preview ?? block

    function startResize(event: PointerEvent<HTMLButtonElement>): void {
        const card = slot.current
        const grid = card?.parentElement
        if (event.button !== 0 || !event.isPrimary || !card || !grid) {
            return
        }
        const gap = parseFloat(getComputedStyle(grid).columnGap)
        const stacked = getComputedStyle(card).getPropertyValue('--app-grid-stacked').trim() === '1'
        start.current = {
            x: event.clientX,
            y: event.clientY,
            height: card.getBoundingClientRect().height,
            columnStep: stacked ? Infinity : (grid.clientWidth + gap) / GRID_COLUMNS,
        }
        event.currentTarget.setPointerCapture(event.pointerId)
    }

    function dragSize(event: PointerEvent<HTMLButtonElement>): CardSize | null {
        if (!start.current || !event.currentTarget.hasPointerCapture(event.pointerId)) {
            return null
        }
        const { x, y, height, columnStep } = start.current
        const columns = Math.round((event.clientX - x) / columnStep)
        const nextWidth = clamp(width + columns, 1, GRID_COLUMNS)
        const dy = event.clientY - y
        const nextHeight =
            Math.abs(dy) < 4 ? block.height : clamp(Math.round(height + dy), MIN_CARD_HEIGHT, MAX_CARD_HEIGHT)
        return nextWidth === width && nextHeight === block.height ? null : { width: nextWidth, height: nextHeight }
    }

    return (
        <div
            ref={slot}
            className={cn('NotebookAppBuilder__slot', size.height !== undefined && 'NotebookAppBuilder__slot--sized')}
            style={{ '--app-block-width': size.width ?? GRID_COLUMNS, height: size.height } as CSSProperties}
            onDragOver={onMove ? (event) => event.preventDefault() : undefined}
            onDrop={
                onMove
                    ? (event) => {
                          event.preventDefault()
                          onMove(event.dataTransfer.getData('application/x-notebook-app-block'), block.id)
                      }
                    : undefined
            }
        >
            <LemonCard
                hoverEffect={false}
                className={cn('h-full min-w-0 p-[var(--app-card-padding,1rem)]', selected && 'border-accent')}
            >
                {toolbar}
                <div className="NotebookAppBuilder__card-body">{children}</div>
                {onResize && (
                    <button
                        type="button"
                        aria-label="Resize component"
                        title="Drag to resize or click for size settings"
                        className="absolute bottom-0 right-0 flex size-6 items-center justify-center cursor-nwse-resize touch-none text-secondary hover:text-primary"
                        data-attr="notebook-app-resize-component"
                        onClick={() => onSelect?.(block.id)}
                        onPointerDown={startResize}
                        onPointerMove={(event) => setPreview(dragSize(event))}
                        onPointerUp={(event) => {
                            const next = dragSize(event)
                            if (next) {
                                onResize(block.id, next)
                            }
                        }}
                        onLostPointerCapture={() => {
                            start.current = null
                            setPreview(null)
                        }}
                    >
                        <IconExpand45 className="rotate-90" />
                    </button>
                )}
            </LemonCard>
        </div>
    )
}
