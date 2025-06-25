import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

const DURATION_REGEX = /^(\d*\.?\d+)([dhm])$/

export function HogFlowDuration({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const parts = value.match(DURATION_REGEX) ?? ['', '10', 'm']
    const [, numberValueString, unit] = parts

    const numberValue = parseFloat(numberValueString)

    return (
        <div className="flex gap-2">
            <LemonInput type="number" value={numberValue} onChange={(v) => onChange(`${v}${unit}`)} />

            <LemonSelect
                options={[
                    { label: 'Minute(s)', value: 'm' },
                    { label: 'Hour(s)', value: 'h' },
                    { label: 'Day(s)', value: 'd' },
                ]}
                value={unit}
                onChange={(v) => onChange(`${numberValue}${v}`)}
            />
        </div>
    )
}
