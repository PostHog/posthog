import { IconDrag } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { StepIcon } from './StepIcon'
import type { PaletteItem } from './tileCanvasModel'
import type { CanvasCommand } from './useCanvasCommands'

export function StepPaletteRow({
    item,
    id,
    index,
    active,
    onHover,
    onChoose,
    onDragStart,
    onDragEnd,
}: {
    item: PaletteItem<CanvasCommand>
    id: string
    index: number
    active: boolean
    onHover: () => void
    onChoose: () => void
    /** Set for a step row on the canvas, which a drag can drop on a +. */
    onDragStart?: () => void
    onDragEnd?: () => void
}): JSX.Element {
    const draggable = item.kind === 'step' && !!onDragStart
    const button = (
        <LemonButton
            fullWidth
            size="small"
            id={id}
            role="option"
            {...{ 'aria-selected': active }}
            data-index={index}
            active={active}
            icon={
                item.kind === 'step' ? (
                    <StepIcon step={item.step} />
                ) : (
                    <span className="flex size-6 shrink-0 items-center justify-center rounded bg-surface-secondary text-[14px]">
                        {item.command.icon}
                    </span>
                )
            }
            sideIcon={draggable && active ? <IconDrag className="text-secondary" /> : undefined}
            onMouseEnter={onHover}
            onClick={onChoose}
        >
            <span className="flex min-w-0 flex-col text-left">
                <span className="text-[13px] font-semibold">{item.label}</span>
                {item.description && (
                    <span className="truncate text-[11.5px] font-normal text-secondary">{item.description}</span>
                )}
            </span>
        </LemonButton>
    )
    if (!draggable) {
        return button
    }
    return (
        <div
            draggable
            onDragStart={(event) => {
                event.dataTransfer.effectAllowed = 'move'
                event.dataTransfer.setData('text/plain', item.label)
                onDragStart?.()
            }}
            onDragEnd={onDragEnd}
        >
            {button}
        </div>
    )
}
