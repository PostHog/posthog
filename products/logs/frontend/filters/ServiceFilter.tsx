import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { projectLogic } from 'scenes/projectLogic'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { ALL_SERVICES_VALUE, logsLogic } from '../logsLogic'

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange, isAllServicesSelected, openServiceFilterRequest } = useValues(logsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsLogic)
    const [isSelectingService, setIsSelectingService] = useState(false)
    const containerRef = useRef<HTMLSpanElement>(null)

    // Listen for requests to open the service filter from other components
    useEffect(() => {
        if (openServiceFilterRequest) {
            setIsSelectingService(true)
        }
    }, [openServiceFilterRequest])

    // Focus the input when switching to selection mode
    useEffect(() => {
        if (isSelectingService) {
            // Small delay to let the component render
            const timer = setTimeout(() => {
                const input = containerRef.current?.querySelector('input')
                input?.focus()
                input?.click()
            }, 50)
            return () => clearTimeout(timer)
        }
    }, [isSelectingService])

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        attribute_type: 'resource',
        dateRange,
    }).url

    if (isAllServicesSelected && !isSelectingService) {
        return (
            <LemonButton size="small" onClick={() => setIsSelectingService(true)} className="min-w-[150px]">
                All services
            </LemonButton>
        )
    }

    return (
        <span ref={containerRef} className="rounded bg-surface-primary min-w-[150px] flex items-stretch">
            <PropertyValue
                size="small"
                endpoint={endpoint}
                operator={PropertyOperator.Exact}
                propertyKey="service_name"
                type={PropertyFilterType.Log}
                value={isAllServicesSelected ? [] : serviceNames}
                onSet={(values) => {
                    if (!values || values.length === 0) {
                        setServiceNames([ALL_SERVICES_VALUE])
                    } else {
                        setServiceNames(values)
                    }
                    setIsSelectingService(false)
                }}
                placeholder="All services"
                preloadValues
            />
        </span>
    )
}
