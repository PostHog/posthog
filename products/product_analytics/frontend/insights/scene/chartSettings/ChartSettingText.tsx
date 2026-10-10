import { useEffect, useId, useState } from 'react'

import { Field, FieldLabel, Input, cn } from '@posthog/quill'

import type { ChartSetting } from './buildChartSettings'

export function ChartSettingText({
    setting,
    onChange,
}: {
    setting: Extract<ChartSetting, { kind: 'text' }>
    onChange: (value: string) => void
}): JSX.Element {
    const id = useId()
    const [draft, setDraft] = useState(setting.value)

    useEffect(() => {
        setDraft(setting.value)
    }, [setting.value])

    // Commit when the field is left, so the chart does not reload on every key press.
    const commit = (): void => {
        if (draft !== setting.value) {
            onChange(draft)
        }
    }

    return (
        <Field orientation="horizontal" className={cn(setting.nested && 'ps-4')}>
            <FieldLabel htmlFor={id}>{setting.label}</FieldLabel>
            <Input
                id={id}
                className="w-40 shrink-0"
                value={draft}
                placeholder={setting.placeholder}
                disabled={!!setting.disabledReason}
                onChange={(event: React.ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Enter') {
                        commit()
                    }
                }}
                data-attr={`quill-insight-chart-setting-${setting.id}`}
            />
        </Field>
    )
}
