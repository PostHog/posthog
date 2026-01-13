import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { projectLogic } from 'scenes/projectLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

import { ALL_SERVICES_VALUE, logsLogic } from '../logsLogic'

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange, isAllServicesSelected, openServiceFilterRequest } = useValues(logsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsLogic)
    const { options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const [isSelectingService, setIsSelectingService] = useState(false)
    const containerRef = useRef<HTMLSpanElement>(null)

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        attribute_type: 'resource',
        dateRange,
    }).url

    const propertyKey = 'service_name'
    const propertyOptions = options[propertyKey]

    // Load service values on mount and when endpoint changes
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

    // Listen for requests to open the service filter from other components
    useEffect(() => {
        if (openServiceFilterRequest) {
            setIsSelectingService(true)
        }
    }, [openServiceFilterRequest])

    // Focus the input when switching to selection mode
    useEffect(() => {
        if (isSelectingService) {
            const timer = setTimeout(() => {
                const input = containerRef.current?.querySelector('input')
                input?.focus()
                input?.click()
            }, 50)
            return () => clearTimeout(timer)
        }
    }, [isSelectingService])

    const selectOptions: LemonInputSelectOption[] = useMemo(() => {
        const allServicesOption: LemonInputSelectOption = {
            key: ALL_SERVICES_VALUE,
            label: 'All services',
        }
        const serviceOptions: LemonInputSelectOption[] = (propertyOptions?.values || []).map(({ name }) => ({
            key: String(name),
            label: String(name),
        }))
        return [allServicesOption, ...serviceOptions]
    }, [propertyOptions?.values])

    const displayValue = useMemo(() => {
        if (isAllServicesSelected) {
            return [ALL_SERVICES_VALUE]
        }
        return serviceNames || []
    }, [isAllServicesSelected, serviceNames])

    const handleChange = (newValue: string[]): void => {
        if (newValue.length === 0 || newValue.includes(ALL_SERVICES_VALUE)) {
            setServiceNames([ALL_SERVICES_VALUE])
        } else {
            setServiceNames(newValue)
        }
        setIsSelectingService(false)
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

    if (isAllServicesSelected && !isSelectingService) {
        return (
            <span
                ref={containerRef}
                className="rounded bg-surface-primary min-w-[150px] flex items-stretch cursor-pointer"
                onClick={() => setIsSelectingService(true)}
            >
                <LemonInputSelect
                    mode="single"
                    size="small"
                    value={displayValue}
                    options={selectOptions}
                    onChange={handleChange}
                    onInputChange={handleSearchChange}
                    placeholder="All services"
                    loading={propertyOptions?.status === 'loading'}
                    allowCustomValues
                />
            </span>
        )
    }

    return (
        <span ref={containerRef} className="rounded bg-surface-primary min-w-[150px] flex items-stretch">
            <LemonInputSelect
                mode="single"
                size="small"
                value={displayValue}
                options={selectOptions}
                onChange={handleChange}
                onInputChange={handleSearchChange}
                placeholder="All services"
                loading={propertyOptions?.status === 'loading'}
                autoFocus={isSelectingService}
                allowCustomValues
            />
        </span>
    )
}
