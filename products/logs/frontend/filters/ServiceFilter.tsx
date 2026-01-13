import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo } from 'react'
import { combineUrl } from 'kea-router'

import { IconWarning } from '@posthog/icons'
import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { projectLogic } from 'scenes/projectLogic'

import { ALL_SERVICES_VALUE, logsLogic } from '../logsLogic'

const ALL_SERVICES_OPTION: LemonInputSelectOption = {
    key: ALL_SERVICES_VALUE,
    label: 'All services (slow)',
}

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange, isAllServicesSelected } = useValues(logsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsLogic)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const { options } = useValues(propertyDefinitionsModel)

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        attribute_type: 'resource',
        dateRange,
    }).url

    const propertyKey = 'service_name'
    const propertyOptions = options[propertyKey]

    const load = useCallback(
        (newInput: string | undefined): void => {
            loadPropertyValues({
                endpoint,
                type: undefined,
                newInput,
                propertyKey,
                eventNames: [],
                properties: [],
            })
        },
        [loadPropertyValues, endpoint, propertyKey]
    )

    useEffect(() => {
        if (propertyOptions?.status !== 'loading' && propertyOptions?.status !== 'loaded') {
            load('')
        }
    }, [propertyKey, load, propertyOptions?.status])

    const displayOptions: LemonInputSelectOption[] = useMemo(() => {
        const apiOptions = (propertyOptions?.values || []).map(({ name }) => ({
            key: String(name),
            label: String(name),
        }))

        // Add the "All services" option at the top
        return [ALL_SERVICES_OPTION, ...apiOptions]
    }, [propertyOptions?.values])

    const handleSearchChange = (newInput: string): void => {
        if (newInput.trim()) {
            load(newInput.trim())
        }
    }

    const handleChange = (values: string[]): void => {
        // If "All services" is selected along with specific services, keep only "All services"
        if (values.includes(ALL_SERVICES_VALUE) && values.length > 1) {
            // If * was just added, select only *
            if (!serviceNames?.includes(ALL_SERVICES_VALUE)) {
                setServiceNames([ALL_SERVICES_VALUE])
            } else {
                // If * was already selected and user selected specific services, remove *
                setServiceNames(values.filter((v) => v !== ALL_SERVICES_VALUE))
            }
        } else {
            setServiceNames(values)
        }
    }

    return (
        <span className="rounded bg-surface-primary min-w-[150px] flex items-center gap-1">
            <LemonInputSelect
                size="small"
                mode="multiple"
                value={serviceNames ?? []}
                onChange={handleChange}
                onInputChange={handleSearchChange}
                options={displayOptions}
                placeholder="Select service"
                loading={propertyOptions?.status === 'loading'}
                allowCustomValues
                data-attr="logs-service-filter"
            />
            {isAllServicesSelected && (
                <span className="text-warning flex items-center gap-0.5 text-xs whitespace-nowrap pr-1">
                    <IconWarning className="text-warning" />
                    Slow
                </span>
            )}
        </span>
    )
}
