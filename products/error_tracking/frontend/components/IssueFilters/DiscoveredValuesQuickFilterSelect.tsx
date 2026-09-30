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

// Controls and property values share one item list. The prefixes keep a property value such as
// "control:any" from acting as a control, because every value item starts with VALUE_PREFIX.
const ANY_ITEM = 'control:any'
const STATUS_ITEM = 'control:status'
const VALUE_PREFIX = 'value:'

function toItem(optionId: string): string {
    return `${VALUE_PREFIX}${optionId}`
}

function fromItem(item: string): string | null {
    return item.startsWith(VALUE_PREFIX) ? item.slice(VALUE_PREFIX.length) : null
}

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
        const valueItems = withSelectedOption(discoveredOptions, selectedOptionId).map((option) => toItem(option.id))
        return [ANY_ITEM, ...valueItems, ...(statusMessage ? [STATUS_ITEM] : [])]
    }, [discoveredOptions, selectedOptionId, statusMessage])

    return (
        <Combobox
            items={items}
            value={selectedOptionId === null ? ANY_ITEM : toItem(selectedOptionId)}
            inputValue={search}
            // Search runs on the server, so the list shows the returned values unfiltered
            filter={null}
            autoHighlight
            highlightItemOnHover
            itemToStringLabel={(item: string) => (item === ANY_ITEM ? anyLabel : (fromItem(item) ?? ''))}
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
            onValueChange={(item: string | null) => {
                if (item === ANY_ITEM) {
                    onChange(null)
                    return
                }
                const optionId = item === null ? null : fromItem(item)
                if (optionId !== null) {
                    onChange(resolveQuickFilterOption(filter, optionId))
                }
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
                    {(item: string) =>
                        item === STATUS_ITEM ? (
                            <ComboboxItem key={item} value={item} disabled className="text-sm">
                                <Text size="sm" variant="muted" className="italic">
                                    {statusMessage}
                                </Text>
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={item} value={item} className="text-sm">
                                <span className="truncate">{item === ANY_ITEM ? anyLabel : fromItem(item)}</span>
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
