import { useId } from 'react'

import { Field, FieldLabel, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, cn } from '@posthog/quill'

import type { ChartSetting } from './buildChartSettings'

export function ChartSettingSelect({
    setting,
    onChange,
}: {
    setting: Extract<ChartSetting, { kind: 'select' }>
    onChange: (value: string) => void
}): JSX.Element {
    const id = useId()

    return (
        <Field orientation="horizontal" className={cn(setting.nested && 'ps-4')}>
            <FieldLabel htmlFor={id}>{setting.label}</FieldLabel>
            <Select
                items={setting.options}
                value={setting.value}
                disabled={!!setting.disabledReason}
                onValueChange={(nextValue) => {
                    if (typeof nextValue === 'string') {
                        onChange(nextValue)
                    }
                }}
            >
                <SelectTrigger
                    id={id}
                    size="sm"
                    className="w-40 shrink-0"
                    data-attr={`quill-insight-chart-setting-${setting.id}`}
                >
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {setting.options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </Field>
    )
}
