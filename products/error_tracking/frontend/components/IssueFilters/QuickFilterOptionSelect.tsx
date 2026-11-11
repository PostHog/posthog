import { useMemo } from 'react'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'lib/ui/quill'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter, QuickFilterOption } from '~/types'

import { DiscoveredValuesQuickFilterSelect } from './DiscoveredValuesQuickFilterSelect'

const ANY_OPTION = '__any__'

interface QuickFilterSelectProps {
    filter: QuickFilter
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

function ManualQuickFilterSelect({ filter, selectedOptionId, onChange }: QuickFilterSelectProps): JSX.Element {
    const items = useMemo(
        () => [
            { value: ANY_OPTION, label: `Any ${filter.name.toLowerCase()}` },
            ...filter.options.map((option) => ({ value: option.id, label: option.label })),
        ],
        [filter.name, filter.options]
    )

    return (
        <Select
            items={items}
            value={selectedOptionId ?? ANY_OPTION}
            onValueChange={(selectedId) => {
                if (selectedId === ANY_OPTION) {
                    onChange(null)
                    return
                }

                const selectedOption = filter.options.find((option: QuickFilterOption) => option.id === selectedId)
                if (selectedOption) {
                    onChange(selectedOption)
                }
            }}
        >
            <SelectTrigger size="default">
                <SelectValue />
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {items.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                        {item.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

/** One quick filter's options, for any caller that keeps the selection itself. */
export function QuickFilterOptionSelect({
    filter,
    context,
    selectedOptionId,
    onChange,
}: QuickFilterSelectProps & { context: QuickFilterContext }): JSX.Element {
    return filter.type === 'auto-discovery' ? (
        <DiscoveredValuesQuickFilterSelect
            filter={filter}
            context={context}
            selectedOptionId={selectedOptionId}
            onChange={onChange}
        />
    ) : (
        <ManualQuickFilterSelect filter={filter} selectedOptionId={selectedOptionId} onChange={onChange} />
    )
}
