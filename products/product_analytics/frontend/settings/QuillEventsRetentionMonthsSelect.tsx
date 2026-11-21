import type {
    LemonSelectOption,
    LemonSelectOptionLeaf,
    LemonSelectOptions,
    LemonSelectSection,
} from '@posthog/lemon-ui'
import {
    Button,
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { isLemonSelectOptionNode, isLemonSelectSection } from 'lib/lemon-ui/LemonSelect/LemonSelect'

export function QuillEventsRetentionMonthsSelect({
    id,
    value,
    options,
    onChange,
    loading,
    disabledReason,
    invalid,
    dataAttr,
}: {
    id: string
    value: number | null
    options: LemonSelectOptions<number | null>
    onChange: (months: number | null) => void
    loading?: boolean
    disabledReason?: string | null
    invalid?: boolean
    dataAttr: string
}): JSX.Element {
    const entries: (LemonSelectSection<number | null> | LemonSelectOption<number | null>)[] = options
    const sections: LemonSelectSection<number | null>[] = entries.every((entry) => isLemonSelectSection(entry))
        ? (options as LemonSelectSection<number | null>[])
        : [{ options: options as LemonSelectOption<number | null>[] }]
    const groups = sections.map((section) =>
        section.options.filter(
            (option): option is LemonSelectOptionLeaf<number | null> => !isLemonSelectOptionNode(option)
        )
    )
    const leaves = groups.flat()

    return (
        <Select<number | null>
            value={value}
            onValueChange={(next) => onChange(next as number | null)}
            disabled={loading}
        >
            <SelectTrigger
                id={id}
                className="w-80 max-w-full"
                aria-invalid={invalid || undefined}
                render={<Button variant="outline" left loading={loading} disabledReason={disabledReason} />}
                data-attr={dataAttr}
            >
                <SelectValue>
                    {(selected: number | null) => leaves.find((option) => option.value === selected)?.label}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {groups.map((group, index) => (
                    <SelectGroup key={index}>
                        {index > 0 && <SelectSeparator />}
                        {group.map((option) => (
                            <SelectItem
                                key={option.value ?? 'default'}
                                value={option.value}
                                disabledReason={option.disabledReason}
                                data-attr={option['data-attr']}
                            >
                                {/* The menu label carries the lock and upgrade hint for periods above the plan limit. */}
                                {typeof option.labelInMenu === 'function'
                                    ? option.label
                                    : (option.labelInMenu ?? option.label)}
                            </SelectItem>
                        ))}
                    </SelectGroup>
                ))}
            </SelectContent>
        </Select>
    )
}
