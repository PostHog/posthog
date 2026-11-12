import { IconFilter, IconTrash } from '@posthog/icons'
import { Badge, Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

export interface ExclusionStepOption {
    value: number
    label: string
}

export interface QuillExclusionRowSuffixProps {
    index: number
    fromStep: number
    toStep: number
    fromOptions: ExclusionStepOption[]
    toOptions: ExclusionStepOption[]
    onFromChange: (fromStep: number) => void
    onToChange: (toStep: number) => void
    disabledReason?: string
    propertyFilterCount: number
    onToggleFilters: () => void
    onClose?: () => void
}

export function QuillExclusionRowSuffix({
    index,
    fromStep,
    toStep,
    fromOptions,
    toOptions,
    onFromChange,
    onToChange,
    disabledReason,
    propertyFilterCount,
    onToggleFilters,
    onClose,
}: QuillExclusionRowSuffixProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 w-full p-1 my-1">
            <div className="flex shrink-0 items-center gap-2">
                <Text size="xs" render={<span />}>
                    between
                </Text>
                <StepSelect
                    value={fromStep}
                    options={fromOptions}
                    onChange={onFromChange}
                    disabledReason={disabledReason}
                />
            </div>
            <div className="flex shrink-0 items-center gap-2">
                <Text size="xs" render={<span />}>
                    and
                </Text>
                <StepSelect value={toStep} options={toOptions} onChange={onToChange} disabledReason={disabledReason} />
            </div>
            <div className="flex items-center gap-1 ml-auto">
                <Button
                    size="icon"
                    className="relative"
                    aria-label="Show filters"
                    tooltip="Show filters"
                    data-attr={`show-prop-filter-${index}`}
                    onClick={onToggleFilters}
                >
                    <IconFilter />
                    {propertyFilterCount > 0 && <Badge className="absolute top-0 right-0">{propertyFilterCount}</Badge>}
                </Button>
                <Button
                    size="icon"
                    aria-label="Delete event exclusion series"
                    tooltip="Delete event exclusion series"
                    data-attr="delete-prop-exclusion-filter"
                    onClick={onClose}
                >
                    <IconTrash />
                </Button>
            </div>
        </div>
    )
}

function StepSelect({
    value,
    options,
    onChange,
    disabledReason,
}: {
    value: number
    options: ExclusionStepOption[]
    onChange: (value: number) => void
    disabledReason?: string
}): JSX.Element {
    return (
        <Select<number>
            value={value}
            onValueChange={(next: number | null) => next !== null && onChange(next)}
            disabled={!!disabledReason}
        >
            <SelectTrigger render={<Button variant="outline" left disabledReason={disabledReason} />}>
                <SelectValue>{(selected: number) => `Step ${selected + 1}`}</SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
