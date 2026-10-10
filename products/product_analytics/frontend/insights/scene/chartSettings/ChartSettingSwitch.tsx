import { useId } from 'react'

import { Field, FieldContent, FieldDescription, FieldLabel, Switch, cn } from '@posthog/quill'

import type { ChartSetting } from './buildChartSettings'

export function ChartSettingSwitch({
    setting,
    onChange,
}: {
    setting: Extract<ChartSetting, { kind: 'switch' }>
    onChange: (checked: boolean) => void
}): JSX.Element {
    const id = useId()

    return (
        <Field orientation="horizontal" className={cn(setting.nested && 'ps-4')}>
            <FieldContent>
                <FieldLabel htmlFor={id}>{setting.label}</FieldLabel>
                {setting.disabledReason && <FieldDescription>{setting.disabledReason}</FieldDescription>}
            </FieldContent>
            <Switch
                id={id}
                size="sm"
                checked={setting.checked}
                disabled={!!setting.disabledReason}
                onCheckedChange={(checked) => onChange(checked)}
                data-attr={`quill-insight-chart-setting-${setting.id}`}
            />
        </Field>
    )
}
