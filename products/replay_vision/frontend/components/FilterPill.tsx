import { LemonButton, LemonButtonWithDropdown, LemonCheckbox } from '@posthog/lemon-ui'

export function FilterPill<T extends string>({
    label,
    options,
    value,
    onChange,
}: {
    label: string
    options: { value: T; label: string }[]
    value: T[]
    onChange: (next: T[]) => void
}): JSX.Element {
    const toggle = (v: T): void => {
        onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
    }
    return (
        <LemonButtonWithDropdown
            type="secondary"
            size="small"
            dropdown={{
                closeOnClickInside: false,
                overlay: options.map((opt) => (
                    <LemonButton key={opt.value} fullWidth onClick={() => toggle(opt.value)}>
                        <LemonCheckbox checked={value.includes(opt.value)} className="pointer-events-none mr-2" />
                        {opt.label}
                    </LemonButton>
                )),
            }}
        >
            {value.length > 0 ? `${label} (${value.length})` : label}
        </LemonButtonWithDropdown>
    )
}
