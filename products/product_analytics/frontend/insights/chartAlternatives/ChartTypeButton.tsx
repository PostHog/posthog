import { LemonButton } from '@posthog/lemon-ui'

import type { ChartDisplayOption } from './chartDisplayOptions'
import { ChartDisplaySketch } from './ChartDisplaySketch'

export function ChartTypeButton({
    current = false,
    disabledReason,
    onClick,
    option,
}: {
    current?: boolean
    disabledReason?: string
    onClick: () => void
    option: ChartDisplayOption
}): JSX.Element {
    return (
        <LemonButton
            fullWidth
            type="secondary"
            active={current}
            className="h-auto min-h-0 items-start whitespace-normal p-2 text-left"
            data-attr={`chart-alternative-${option.display}`}
            aria-pressed={current}
            disabledReason={disabledReason ?? option.disabledReason}
            onClick={onClick}
        >
            <span className="flex w-full flex-col gap-1">
                <span className="flex h-16 items-center justify-center">
                    <span className="w-28">
                        <ChartDisplaySketch display={option.display} />
                    </span>
                </span>
                <span className="font-medium">{option.label}</span>
                <span className="text-xs font-normal text-secondary">{option.description}</span>
            </span>
        </LemonButton>
    )
}
