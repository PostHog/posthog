import { useEffect, useId, useState } from 'react'

import { Field, FieldContent, FieldDescription, FieldError, FieldLabel, Input, Text, cn } from '@posthog/quill'

import type { ChartSetting } from './buildChartSettings'

function asDraft(value: number | null): string {
    return value === null ? '' : String(value)
}

export function ChartSettingNumber({
    setting,
    onChange,
}: {
    setting: Extract<ChartSetting, { kind: 'number' }>
    onChange: (value: number | null) => void
}): JSX.Element {
    const id = useId()
    const [draft, setDraft] = useState(asDraft(setting.value))

    useEffect(() => {
        setDraft(asDraft(setting.value))
    }, [setting.value])

    // Commit when the field is left. A number input reads as empty while a value is typed, which would clear it.
    const commit = (): void => {
        const parsed = draft.trim() === '' ? null : Number(draft)
        if (parsed !== null && !Number.isFinite(parsed)) {
            setDraft(asDraft(setting.value))
            return
        }
        const rounded = parsed !== null && setting.integer ? Math.round(parsed) : parsed
        const bounded =
            rounded === null ? null : Math.min(Math.max(rounded, setting.min ?? -Infinity), setting.max ?? Infinity)
        setDraft(asDraft(bounded))
        if (bounded !== setting.value) {
            onChange(bounded)
        }
    }

    return (
        <Field
            orientation="horizontal"
            className={cn(setting.nested && 'ps-4')}
            data-invalid={setting.error ? 'true' : undefined}
        >
            <FieldContent>
                <FieldLabel htmlFor={id}>{setting.label}</FieldLabel>
                {setting.disabledReason && <FieldDescription>{setting.disabledReason}</FieldDescription>}
                {setting.error && <FieldError>{setting.error}</FieldError>}
            </FieldContent>
            <div className="flex shrink-0 items-center gap-2">
                <Input
                    id={id}
                    type="number"
                    className="w-24"
                    value={draft}
                    placeholder={setting.placeholder}
                    min={setting.min}
                    max={setting.max}
                    step={setting.integer ? 1 : 'any'}
                    disabled={!!setting.disabledReason}
                    aria-invalid={setting.error ? true : undefined}
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
                    onBlur={commit}
                    onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                        if (event.key === 'Enter') {
                            commit()
                        }
                    }}
                    data-attr={`quill-insight-chart-setting-${setting.id}`}
                />
                {setting.suffix && (
                    <Text size="xs" variant="muted" render={<span />}>
                        {setting.suffix}
                    </Text>
                )}
            </div>
        </Field>
    )
}
