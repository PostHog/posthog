import { ExperimentStatsMethod } from '~/types'

import { SelectableCard } from './SelectableCard'
import { STATS_METHOD_OPTIONS } from './statsMethodOptions'

export interface StatsMethodSelectorProps {
    value: ExperimentStatsMethod
    onChange: (method: ExperimentStatsMethod) => void
    disabled?: boolean
    disabledReason?: string
}

export function StatsMethodSelector({
    value,
    onChange,
    disabled,
    disabledReason,
}: StatsMethodSelectorProps): JSX.Element {
    const isDisabled = disabled ?? false
    const reason = disabledReason ?? ''
    const disabledProps = isDisabled ? { disabled: true, disabledReason: reason || 'Disabled' } : {}

    return (
        <div className="flex gap-4 max-w-[800px]">
            {STATS_METHOD_OPTIONS.map((option) => (
                <SelectableCard
                    key={option.value}
                    title={option.title}
                    description={option.description}
                    selected={value === option.value}
                    onClick={() => !isDisabled && onChange(option.value)}
                    {...disabledProps}
                />
            ))}
        </div>
    )
}
