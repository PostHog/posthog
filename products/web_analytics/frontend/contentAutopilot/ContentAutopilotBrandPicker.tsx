import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import type { BrandPickerGroup } from './brandDetail'

/** Switches the brand page to another brand of the catalog, keeping the filters. */
export const ContentAutopilotBrandPicker = ({
    brandId,
    groups,
    onChange,
}: {
    brandId: string
    groups: BrandPickerGroup[]
    onChange: (brandId: string) => void
}): JSX.Element => {
    const options = groups.flatMap((group) => group.options)
    return (
        <Select<string> value={brandId} onValueChange={(next) => next && next !== brandId && onChange(next)}>
            <SelectTrigger aria-label="Change brand" data-attr="content-autopilot-brand-picker">
                <SelectValue>
                    {(value: string | null) => options.find((option) => option.id === value)?.name ?? 'Change brand'}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {groups.map((group) => (
                    <SelectGroup key={group.label}>
                        <SelectGroupLabel>{group.label}</SelectGroupLabel>
                        {group.options.map((option) => (
                            <SelectItem key={option.id} value={option.id}>
                                {option.name}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                ))}
            </SelectContent>
        </Select>
    )
}
