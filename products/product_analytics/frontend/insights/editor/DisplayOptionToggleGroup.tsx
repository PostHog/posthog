import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export interface DisplayOptionToggleGroupProps<T extends string | number> {
    value: T
    options: { value: T; label: string }[]
    onChange: (value: T) => void
}

export function DisplayOptionToggleGroup<T extends string | number>({
    value,
    options,
    onChange,
}: DisplayOptionToggleGroupProps<T>): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <ToggleGroup
                className="w-full"
                value={[String(value)]}
                onValueChange={(next: string[]) => {
                    const picked = options.find((option) => String(option.value) === next[0])
                    if (picked) {
                        onChange(picked.value)
                    }
                }}
            >
                {options.map((option) => (
                    <ToggleGroupItem key={String(option.value)} value={String(option.value)} className="flex-1">
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        )
    }

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            onChange={onChange}
            value={value}
            options={options}
            size="small"
            fullWidth
        />
    )
}
