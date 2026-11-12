import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

export interface FunnelAttributionOption {
    value: string
    label: string
    hidden?: boolean
}

export interface QuillFunnelAttributionSelectProps {
    value: string
    touchpointOptions: FunnelAttributionOption[]
    specificStep: { label: string; options: FunnelAttributionOption[]; hidden: boolean }
    onChange: (value: string) => void
}

export function QuillFunnelAttributionSelect({
    value,
    touchpointOptions,
    specificStep,
    onChange,
}: QuillFunnelAttributionSelectProps): JSX.Element {
    const allOptions = [...touchpointOptions, ...specificStep.options]
    const isVisible = (option: FunnelAttributionOption): boolean => !option.hidden

    return (
        <Select<string> value={value} onValueChange={(next: string | null) => next !== null && onChange(next)}>
            <SelectTrigger data-attr="breakdown-attributions">
                <SelectValue>
                    {(selected: string) => allOptions.find((option) => option.value === selected)?.label ?? selected}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {touchpointOptions.filter(isVisible).map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
                {!specificStep.hidden && (
                    <SelectGroup>
                        <SelectGroupLabel>{specificStep.label}</SelectGroupLabel>
                        {specificStep.options.filter(isVisible).map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                )}
            </SelectContent>
        </Select>
    )
}
