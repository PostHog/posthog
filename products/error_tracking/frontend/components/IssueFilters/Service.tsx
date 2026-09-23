import { useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

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
const EXCEPTION_EVENT_NAMES = ['$exception']
const ALL_SERVICES_VALUE = '__all__'

export const ServiceFilter = (): JSX.Element | null => {
    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const { filterGroup } = useValues(issueFiltersLogic)
    const { addPropertyFilter, removePropertyFilter } = useActions(issueFiltersLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)

    useOnMountEffect(() => {
        loadPropertyValues({
            endpoint: undefined,
            type: PropertyDefinitionType.Event,
            newInput: undefined,
            propertyKey: SERVICE_PROPERTY,
            eventNames: EXCEPTION_EVENT_NAMES,
        })
    })

    const option = options[SERVICE_PROPERTY]
    const selected = getEventPropertyFilterValue(filterGroup, SERVICE_PROPERTY)
    const items = useMemo(() => {
        const names = (option?.values ?? [])
            .map(({ name }) => (typeof name === 'string' ? name : ''))
            .filter((name) => name !== '')
        return [ALL_SERVICES_VALUE, ...(selected && !names.includes(selected) ? [selected] : []), ...names]
    }, [option?.values, selected])

    // A project that never sets the property would only ever see an empty control, so hide it.
    if (items.length === 1 && option?.status === 'loaded') {
        return null
    }

    return (
        <Combobox
            items={items}
            value={selected ?? ALL_SERVICES_VALUE}
            onValueChange={(next: string | null) => {
                if (next === null) {
                    return
                }
                if (next === ALL_SERVICES_VALUE) {
                    removePropertyFilter(SERVICE_PROPERTY)
                    return
                }
                addPropertyFilter(SERVICE_PROPERTY, next, undefined, false, true)
            }}
            open={open}
            onOpenChange={setOpen}
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
                            {item === ALL_SERVICES_VALUE ? 'All services' : item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
