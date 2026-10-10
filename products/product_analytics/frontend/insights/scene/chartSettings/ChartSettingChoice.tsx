import { useId } from 'react'

import { Field, FieldLabel, ToggleGroup, ToggleGroupItem, cn } from '@posthog/quill'

import type { ChartSetting } from './buildChartSettings'

export function ChartSettingChoice({
    setting,
    onChange,
}: {
    setting: Extract<ChartSetting, { kind: 'choice' }>
    onChange: (value: string) => void
}): JSX.Element {
    const labelId = useId()
    // More than two options do not fit beside the label in a narrow panel.
    const stacked = setting.options.length > 2

    return (
        <Field orientation={stacked ? 'vertical' : 'horizontal'} className={cn(setting.nested && 'ps-4')}>
            <FieldLabel id={labelId}>{setting.label}</FieldLabel>
            <ToggleGroup
                aria-labelledby={labelId}
                variant="outline"
                size="sm"
                value={[setting.value]}
                disabled={!!setting.disabledReason}
                onValueChange={([nextValue]) => {
                    // Pressing the selected option reports an empty list, and one option must stay selected.
                    if (typeof nextValue === 'string') {
                        onChange(nextValue)
                    }
                }}
                className={cn(stacked && 'w-full')}
            >
                {setting.options.map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        className={cn(stacked && 'flex-1')}
                        data-attr={`quill-insight-chart-setting-${setting.id}-${option.value}`}
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </Field>
    )
}
