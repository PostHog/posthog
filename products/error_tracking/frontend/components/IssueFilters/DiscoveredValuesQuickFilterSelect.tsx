import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconSearch } from '@posthog/icons'

import { resolveQuickFilterOption, withSelectedOption } from 'lib/components/QuickFilters/quickFilterOptions'
import { quickFilterValuesLogic } from 'lib/components/QuickFilters/quickFilterValuesLogic'
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
const LOADING_VALUE = '__loading__'
const ERROR_VALUE = '__error__'
const EMPTY_VALUE = '__empty__'
const STATUS_VALUES = [LOADING_VALUE, ERROR_VALUE, EMPTY_VALUE]

function statusMessage(statusValue: string, search: string): string {
    if (statusValue === LOADING_VALUE) {
        return 'Loading values…'
    }
    if (statusValue === ERROR_VALUE) {
        return "Couldn't load values. Close and reopen the dropdown to try again."
    }
    return search ? 'No matching values in the last 7 days' : 'No values found in the last 7 days'
}

export interface DiscoveredValuesQuickFilterSelectProps {
    filter: QuickFilter
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

export function DiscoveredValuesQuickFilterSelect({
    filter,
    selectedOptionId,
    onChange,
}: DiscoveredValuesQuickFilterSelectProps): JSX.Element {
    const valuesLogic = quickFilterValuesLogic({
        context: QuickFilterContext.ErrorTrackingIssueFilters,
        propertyName: filter.property_name,
    })
    const { discoveredOptions, discoveredValuesStatus, search } = useValues(valuesLogic)
    const { setSearch } = useActions(valuesLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const anyLabel = `Any ${filter.name.toLowerCase()}`

    const items = useMemo(() => {
        const optionIds = withSelectedOption(discoveredOptions, selectedOptionId).map((option) => option.id)
        let statusItem: string | null = null
        if (discoveredValuesStatus === 'loading') {
            statusItem = LOADING_VALUE
        } else if (discoveredValuesStatus === 'error') {
            statusItem = ERROR_VALUE
        } else if (discoveredOptions.length === 0) {
            statusItem = EMPTY_VALUE
        }
        return [ANY_VALUE, ...optionIds, ...(statusItem ? [statusItem] : [])]
    }, [discoveredOptions, discoveredValuesStatus, selectedOptionId])

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
                if (!value || STATUS_VALUES.includes(value)) {
                    return
                }
                onChange(value === ANY_VALUE ? null : resolveQuickFilterOption(filter, value))
            }}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={<Button variant="outline" size="default" left className="justify-between gap-3" />}
                aria-label={filter.name}
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
                        STATUS_VALUES.includes(value) ? (
                            <ComboboxItem key={value} value={value} disabled className="text-sm">
                                <Text size="sm" variant="muted" className="italic">
                                    {statusMessage(value, search)}
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
