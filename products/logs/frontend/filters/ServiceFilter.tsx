import { IconWarning } from '@posthog/icons'
import { LemonInputSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useEffect, useState } from 'react'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { ALL_SERVICES_VALUE, logsLogic } from '../logsLogic'

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange, isAllServicesSelected } = useValues(logsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsLogic)
    const [availableServices, setAvailableServices] = useState<string[]>([])
    const [loading, setLoading] = useState(false)

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        attribute_type: 'resource',
        dateRange,
    }).url

    useEffect(() => {
        const fetchServices = async (): Promise<void> => {
            setLoading(true)
            try {
                const response = await api.get(endpoint)
                setAvailableServices(response || [])
            } catch (error) {
                console.error('Failed to fetch service names:', error)
            } finally {
                setLoading(false)
            }
        }
        fetchServices()
    }, [endpoint])

    const handleChange = (newValues: string[]): void => {
        // If "All services" is being added
        if (newValues.includes(ALL_SERVICES_VALUE) && !serviceNames?.includes(ALL_SERVICES_VALUE)) {
            // Replace everything with just "All services"
            setServiceNames([ALL_SERVICES_VALUE])
        }
        // If a specific service is being added while "All services" is selected
        else if (serviceNames?.includes(ALL_SERVICES_VALUE) && newValues.length > 1) {
            // Remove "All services" and keep only the specific services
            setServiceNames(newValues.filter((v) => v !== ALL_SERVICES_VALUE))
        }
        // Normal case
        else {
            setServiceNames(newValues)
        }
    }

    const options = [
        {
            key: ALL_SERVICES_VALUE,
            label: 'All services',
            labelComponent: (
                <span className="flex items-center gap-1">
                    All services
                    <span className="text-warning flex items-center gap-0.5 text-xs">
                        <IconWarning className="text-base" />
                        Slow
                    </span>
                </span>
            ),
        },
        ...availableServices.map((service) => ({
            key: service,
            label: service,
        })),
    ]

    return (
        <span className="rounded bg-surface-primary min-w-[150px] flex items-stretch">
            <LemonInputSelect
                mode="multiple"
                size="small"
                value={serviceNames || []}
                onChange={handleChange}
                options={options}
                placeholder="Select service"
                loading={loading}
            />
        </span>
    )
}
