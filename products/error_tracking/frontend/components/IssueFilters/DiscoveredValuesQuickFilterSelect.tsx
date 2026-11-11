import clsx from 'clsx'
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

import { ANY_ITEM, STATUS_ITEM, discoveredValuesComboboxItems } from './discoveredValuesComboboxItems'

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
    const selectedOption = selectedOptionId ? resolveQuickFilterOption(filter, selectedOptionId) : null
    const selectedLabel = selectedOption?.label ?? anyLabel

    const labelByItem = useMemo(
        () =>
            new Map(withSelectedOption(discoveredOptions, selectedOptionId).map((option) => [option.id, option.label])),
        [discoveredOptions, selectedOptionId]
    )
    const items = useMemo(
        () =>
            discoveredValuesComboboxItems({
                search,
                discoveredOptions,
                selectedOptionId,
                showStatus: !!statusMessage,
            }),
        [search, discoveredOptions, selectedOptionId, statusMessage]
    )

    return (
        <Combobox
            items={items}
            value={selectedOption ? selectedOption.id : ANY_ITEM}
            inputValue={search}
            // Search runs on the server, so the list shows the returned values unfiltered
            filter={null}
            autoHighlight
            highlightItemOnHover
            itemToStringLabel={(item: string) => (item === ANY_ITEM ? anyLabel : (labelByItem.get(item) ?? ''))}
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
                const option = item === null || item === STATUS_ITEM ? null : resolveQuickFilterOption(filter, item)
                if (option) {
                    onChange(option)
                }
            }}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button
                        variant="outline"
                        size="default"
                        left
                        // Discovered values are raw event data, so keep them out of autocapture and replay
                        className={clsx('justify-between gap-3', selectedOption && 'ph-no-capture')}
                        title={selectedLabel}
                    />
                }
                aria-label={`${filter.name}: ${selectedLabel}`}
            >
                <span className="max-w-60 truncate">{selectedLabel}</span>
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
                    {(item: string) => {
                        if (item === STATUS_ITEM) {
                            return (
                                <ComboboxItem key={item} value={item} disabled className="text-sm">
                                    <Text size="sm" variant="muted" className="italic">
                                        {statusMessage}
                                    </Text>
                                </ComboboxItem>
                            )
                        }
                        if (item === ANY_ITEM) {
                            return (
                                <ComboboxItem key={item} value={item} className="text-sm">
                                    {anyLabel}
                                </ComboboxItem>
                            )
                        }
                        // A plain string child lets ComboboxItem set a title, so a truncated value shows in full on hover
                        return (
                            <ComboboxItem key={item} value={item} className="text-sm ph-no-capture">
                                {labelByItem.get(item) ?? ''}
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
