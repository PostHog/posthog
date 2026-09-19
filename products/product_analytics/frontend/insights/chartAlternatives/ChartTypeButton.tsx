import { LemonButton } from '@posthog/lemon-ui'

import type { ChartDisplayOption } from './chartDisplayOptions'
import { ChartDisplaySketch } from './ChartDisplaySketch'

export function ChartTypeButton({
    compact = false,
    current = false,
    disabledReason,
    onClick,
    option,
}: {
    compact?: boolean
    current?: boolean
    disabledReason?: string
    onClick: () => void
    option: ChartDisplayOption
}): JSX.Element {
    const content = compact ? (
        <span className="flex w-full min-w-0 items-center gap-1.5">
            <span className="w-12 shrink-0 overflow-hidden">
                <ChartDisplaySketch display={option.display} />
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
                <span className="font-medium">{option.label}</span>
                <span className="text-xs font-normal text-secondary line-clamp-2">{option.description}</span>
            </span>
        </span>
    ) : (
        <span className="flex w-full flex-col gap-1">
            <span className="flex h-16 items-center justify-center">
                <span className="w-28">
                    <ChartDisplaySketch display={option.display} />
                </span>
            </span>
            <span className="font-medium">{option.label}</span>
            <span className="text-xs font-normal text-secondary">{option.description}</span>
        </span>
    )

    return (
        <LemonButton
            fullWidth
            size={compact ? 'small' : undefined}
            type="secondary"
            active={current}
            className={
                compact
                    ? 'h-auto min-h-0 justify-start whitespace-normal p-1.5 text-left'
                    : 'h-auto min-h-0 items-start whitespace-normal p-2 text-left'
            }
            data-attr={`chart-alternative-${option.display}`}
            aria-pressed={current}
            disabledReason={disabledReason ?? option.disabledReason}
            onClick={onClick}
        >
            {content}
        </LemonButton>
    )
}
