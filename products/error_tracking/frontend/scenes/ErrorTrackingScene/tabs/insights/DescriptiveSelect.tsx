import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

export interface DescriptiveSelectOption<T extends string> {
    value: T
    label: string
    description: string
}

export function DescriptiveSelect<T extends string>({
    value,
    onChange,
    options,
}: {
    value: T
    onChange: (value: T) => void
    options: DescriptiveSelectOption<T>[]
}): JSX.Element {
    const current = options.find((o) => o.value === value)

    return (
        <LemonMenu
            items={options.map((option) => ({
                label: (
                    <div className="py-0.5 max-w-48">
                        <div className="font-medium text-xs">{option.label}</div>
                        <div className="text-xs text-secondary whitespace-normal">{option.description}</div>
                    </div>
                ),
                onClick: () => onChange(option.value),
                active: option.value === value,
                custom: true,
            }))}
        >
            <LemonButton size="xsmall" type="secondary">
                {current?.label ?? 'Select...'}
            </LemonButton>
        </LemonMenu>
    )
}
