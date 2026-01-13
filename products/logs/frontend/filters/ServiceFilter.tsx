import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { projectLogic } from 'scenes/projectLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { ALL_SERVICES_VALUE, logsLogic } from '../logsLogic'

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange } = useValues(logsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsLogic)
    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        attribute_type: 'resource',
        dateRange,
    }).url

    const propertyKey = 'service_name'
    const propertyOptions = options[propertyKey]

    useEffect(() => {
        if (propertyOptions?.status !== 'loading' && propertyOptions?.status !== 'loaded') {
            loadPropertyValues({
                endpoint,
                type: 'log',
                newInput: '',
                propertyKey,
                eventNames: [],
                properties: [],
            })
        }
    }, [endpoint, loadPropertyValues, propertyOptions?.status])

    const selectOptions: LemonInputSelectOption[] = useMemo(() => {
        const allServicesOption: LemonInputSelectOption = {
            key: ALL_SERVICES_VALUE,
            label: 'All services',
            labelComponent: <strong>All services</strong>,
        }
        const serviceOptions: LemonInputSelectOption[] = (propertyOptions?.values || []).map(({ name }) => ({
            key: String(name),
            label: String(name),
        }))
        return [allServicesOption, ...serviceOptions]
    }, [propertyOptions?.values])

    const currentHasAllServices = serviceNames?.includes(ALL_SERVICES_VALUE) ?? false

    const handleChange = (newValue: string[]): void => {
        if (newValue.length === 0) {
            // Nothing selected, default to all services
            setServiceNames([ALL_SERVICES_VALUE])
        } else if (newValue.includes(ALL_SERVICES_VALUE)) {
            if (!currentHasAllServices) {
                // User explicitly selected "All services" - clear other selections
                setServiceNames([ALL_SERVICES_VALUE])
            } else if (newValue.length > 1) {
                // User added a specific service while "All services" was selected - remove "All services"
                setServiceNames(newValue.filter((v) => v !== ALL_SERVICES_VALUE))
            } else {
                setServiceNames(newValue)
            }
        } else {
            setServiceNames(newValue)
        }
    }

    const handleSearchChange = (searchTerm: string): void => {
        loadPropertyValues({
            endpoint,
            type: 'log',
            newInput: searchTerm.trim(),
            propertyKey,
            eventNames: [],
            properties: [],
        })
    }

    return (
        <span className="rounded bg-surface-primary min-w-[150px] flex items-stretch">
            <LemonInputSelect
                mode="multiple"
                size="small"
                value={serviceNames || []}
                options={selectOptions}
                onChange={handleChange}
                onInputChange={handleSearchChange}
                placeholder="Service name"
                loading={propertyOptions?.status === 'loading'}
                allowCustomValues
            />
        </span>
    )
}
