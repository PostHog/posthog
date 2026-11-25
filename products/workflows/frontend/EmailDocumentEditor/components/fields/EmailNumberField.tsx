import { EmailFieldRow } from './EmailFieldRow'
import { EmailNumberInput } from './EmailNumberInput'
import { NumberLimit } from './numberLimits'

export function EmailNumberField({
    label,
    value,
    placeholder,
    suffix = 'px',
    limit,
    onChange,
    attr,
}: {
    label: string
    value: number | undefined
    placeholder?: number | string
    suffix?: string
    limit: NumberLimit
    onChange: (value: number | undefined) => void
    attr?: string
}): JSX.Element {
    return (
        <EmailFieldRow label={label}>
            <EmailNumberInput
                fullWidth
                limit={limit}
                unit={suffix}
                value={value}
                placeholder={placeholder === undefined ? undefined : String(placeholder)}
                suffix={<span className="text-xs text-secondary">{suffix}</span>}
                onChange={onChange}
                data-attr={attr}
            />
        </EmailFieldRow>
    )
}
