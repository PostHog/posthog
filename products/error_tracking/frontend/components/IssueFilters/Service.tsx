import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconSearch } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    InputGroupAddon,
    SelectTriggerIcon,
} from 'lib/ui/quill'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType } from '~/types'

import { getEventPropertyFilterValue, issueFiltersLogic } from './issueFiltersLogic'

export const SERVICE_PROPERTY = 'service'
const ALL_SERVICES_VALUE = 'all'
// Prefixed so no real service name can collide with the all-services item.
const SERVICE_ITEM_PREFIX = 'service:'

function itemLabel(item: string): string {
    return item === ALL_SERVICES_VALUE ? 'All services' : item.slice(SERVICE_ITEM_PREFIX.length)
}

export const ServiceFilter = (): JSX.Element | null => {
    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const { filterGroup } = useValues(issueFiltersLogic)
    const { addPropertyFilter, removePropertyFilter } = useActions(issueFiltersLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const option = options[SERVICE_PROPERTY]

    // The model does not dedupe, so an already loaded key would refetch on every mount.
    useOnMountEffect(() => {
        if (option?.status === 'loading' || option?.status === 'loaded') {
            return
        }
        loadPropertyValues({
            endpoint: undefined,
            type: PropertyDefinitionType.Event,
            newInput: undefined,
            propertyKey: SERVICE_PROPERTY,
            eventNames: ['$exception'],
        })
    })

    const selected = getEventPropertyFilterValue(filterGroup, SERVICE_PROPERTY)
    const items = useMemo(() => {
        const names = (option?.values ?? [])
            .map(({ name }) => (typeof name === 'string' ? name : ''))
            .filter((name) => name !== '')
        // Keep a selection restored from the URL pickable even before its value load lands.
        if (selected && !names.includes(selected)) {
            names.unshift(selected)
        }
        return [ALL_SERVICES_VALUE, ...names.map((name) => `${SERVICE_ITEM_PREFIX}${name}`)]
    }, [option?.values, selected])

    // A project that never sets the property would only ever see an empty control, so hide it.
    if (items.length === 1 && option?.status === 'loaded') {
        return null
    }

    return (
        <Combobox
            items={items}
            value={selected === null ? ALL_SERVICES_VALUE : `${SERVICE_ITEM_PREFIX}${selected}`}
            itemToStringLabel={itemLabel}
            onValueChange={(next: string | null) => {
                if (next === null) {
                    return
                }
                if (next === ALL_SERVICES_VALUE) {
                    removePropertyFilter(SERVICE_PROPERTY)
                    return
                }
                addPropertyFilter(SERVICE_PROPERTY, next.slice(SERVICE_ITEM_PREFIX.length), undefined, false, true)
            }}
        >
            <ComboboxTrigger
                render={
                    <Button
                        ref={triggerRef}
                        variant="outline"
                        size="default"
                        className="max-w-60"
                        aria-label="Service filter"
                        data-attr="error-tracking-service-filter"
                    >
                        <span className="min-w-0 truncate">{selected ?? 'All services'}</span>
                        <SelectTriggerIcon />
                    </Button>
                }
            />
            <ComboboxContent
                anchor={triggerRef}
                align="start"
                className="w-56 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput placeholder="Search services" showTrigger={false} className="h-7 [&_input]:text-sm">
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxEmpty className="text-sm">No matches</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item}>
                            {itemLabel(item)}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
