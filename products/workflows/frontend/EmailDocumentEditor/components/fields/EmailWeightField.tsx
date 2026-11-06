import { LemonSelect } from '@posthog/lemon-ui'

import { EmailFieldRow } from './EmailFieldRow'

const WEIGHTS = [
    { value: 300, label: 'Light' },
    { value: 400, label: 'Regular' },
    { value: 500, label: 'Medium' },
    { value: 600, label: 'Semibold' },
    { value: 700, label: 'Bold' },
    { value: 800, label: 'Extra bold' },
    { value: 900, label: 'Black' },
]

export function EmailWeightField({
    value,
    fallback,
    onChange,
    attr,
}: {
    value: number | undefined
    fallback: number
    onChange: (value: number) => void
    attr?: string
}): JSX.Element {
    return (
        <EmailFieldRow label="Weight">
            <LemonSelect
                size="small"
                fullWidth
                value={value ?? fallback}
                options={WEIGHTS}
                onChange={onChange}
                data-attr={attr}
            />
        </EmailFieldRow>
    )
}
