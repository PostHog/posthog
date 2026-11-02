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
}: {
    item: PaletteItem<CanvasCommand>
    id: string
    index: number
    active: boolean
    onHover: () => void
    onChoose: () => void
}): JSX.Element {
    return (
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
}
