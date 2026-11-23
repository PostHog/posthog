import { LemonInput } from '@posthog/lemon-ui'

import { EmailFieldRow } from './EmailFieldRow'

export function EmailNumberField({
    label,
    value,
    placeholder,
    suffix = 'px',
    min = 0,
    max,
    onChange,
    attr,
}: {
    label: string
    value: number | undefined
    placeholder?: number | string
    suffix?: string
    min?: number
    max?: number
    onChange: (value: number | undefined) => void
    attr?: string
}): JSX.Element {
    return (
        <EmailFieldRow label={label}>
            <LemonInput
                type="number"
                size="small"
                fullWidth
                min={min}
                max={max}
                // An empty string keeps the input controlled while it shows the placeholder.
                value={value ?? ('' as unknown as number)}
                placeholder={placeholder === undefined ? undefined : String(placeholder)}
                suffix={<span className="text-xs text-secondary">{suffix}</span>}
                onChange={(next) => onChange(next === undefined || Number.isNaN(next) ? undefined : next)}
                data-attr={attr}
            />
        </EmailFieldRow>
    )
}
