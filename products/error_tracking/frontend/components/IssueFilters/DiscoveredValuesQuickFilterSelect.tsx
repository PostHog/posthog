import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconSearch } from '@posthog/icons'

import { resolveQuickFilterOption, withSelectedOption } from 'lib/components/QuickFilters/quickFilterOptions'
import { discoveredValuesMessage, quickFilterValuesLogic } from 'lib/components/QuickFilters/quickFilterValuesLogic'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    InputGroupAddon,
    Text,
} from 'lib/ui/quill'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter, QuickFilterOption } from '~/types'

const ANY_VALUE = '__any__'
const STATUS_VALUE = '__status__'

export interface DiscoveredValuesQuickFilterSelectProps {
    filter: QuickFilter
    context: QuickFilterContext
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

export function DiscoveredValuesQuickFilterSelect({
    filter,
    context,
    selectedOptionId,
    onChange,
}: DiscoveredValuesQuickFilterSelectProps): JSX.Element {
    const valuesLogic = quickFilterValuesLogic({ context, propertyName: filter.property_name })
    const { discoveredOptions, discoveredValuesStatus, search } = useValues(valuesLogic)
    const { setSearch } = useActions(valuesLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const anyLabel = `Any ${filter.name.toLowerCase()}`
    const statusMessage = discoveredValuesMessage(discoveredValuesStatus, search, discoveredOptions.length)

    const items = useMemo(() => {
        const optionIds = withSelectedOption(discoveredOptions, selectedOptionId).map((option) => option.id)
        return [ANY_VALUE, ...optionIds, ...(statusMessage ? [STATUS_VALUE] : [])]
    }, [discoveredOptions, selectedOptionId, statusMessage])

    return (
        <Combobox
            items={items}
            value={selectedOptionId ?? ANY_VALUE}
            inputValue={search}
            // Search runs on the server, so the list shows the returned values unfiltered
            filter={null}
            autoHighlight
            highlightItemOnHover
            itemToStringLabel={(value: string) => (value === ANY_VALUE ? anyLabel : value)}
            onInputValueChange={(value: string, { reason }) => {
                if (reason === 'input-change' || reason === 'input-clear') {
                    setSearch(value)
                }
            }}
            onOpenChange={(open: boolean) => {
                if (open) {
                    setSearch('')
                }
            }}
            onValueChange={(value: string | null) => {
                if (!value || value === STATUS_VALUE) {
                    return
                }
                onChange(value === ANY_VALUE ? null : resolveQuickFilterOption(filter, value))
            }}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={<Button variant="outline" size="default" left className="justify-between gap-3" />}
                aria-label={`${filter.name}: ${selectedOptionId ?? anyLabel}`}
            >
                <span className="max-w-60 truncate">{selectedOptionId ?? anyLabel}</span>
            </ComboboxTrigger>
            <ComboboxContent
                anchor={triggerRef}
                align="start"
                className="w-64 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput
                    placeholder="Search values"
                    autoFocus
                    showTrigger={false}
                    className="h-7 [&_input]:text-sm"
                >
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxList>
                    {(value: string) =>
                        value === STATUS_VALUE ? (
                            <ComboboxItem key={value} value={value} disabled className="text-sm">
                                <Text size="sm" variant="muted" className="italic">
                                    {statusMessage}
                                </Text>
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={value} value={value} className="text-sm">
                                <span className="truncate">{value === ANY_VALUE ? anyLabel : value}</span>
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
