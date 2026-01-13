import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { projectLogic } from 'scenes/projectLogic'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { ALL_SERVICES_VALUE, logsLogic } from '../logsLogic'

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange, isAllServicesSelected } = useValues(logsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsLogic)

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        attribute_type: 'resource',
        dateRange,
    }).url

    if (isAllServicesSelected) {
        return (
            <LemonDropdown
                overlay={
                    <div className="p-2 w-64">
                        <PropertyValue
                            size="small"
                            endpoint={endpoint}
                            operator={PropertyOperator.Exact}
                            propertyKey="service_name"
                            type={PropertyFilterType.Log}
                            value={[]}
                            onSet={(values) => {
                                if (values && values.length > 0) {
                                    setServiceNames(values)
                                }
                            }}
                            placeholder="Search services..."
                            preloadValues
                        />
                    </div>
                }
                placement="bottom-start"
            >
                <LemonInput size="small" value="All services" readOnly className="cursor-pointer min-w-[150px]" />
            </LemonDropdown>
        )
    }

    return (
        <span className="rounded bg-surface-primary min-w-[150px] flex items-stretch">
            <PropertyValue
                size="small"
                endpoint={endpoint}
                operator={PropertyOperator.Exact}
                propertyKey="service_name"
                type={PropertyFilterType.Log}
                value={serviceNames}
                onSet={(values) => {
                    if (!values || values.length === 0) {
                        setServiceNames([ALL_SERVICES_VALUE])
                    } else {
                        setServiceNames(values)
                    }
                }}
                placeholder="All services"
                preloadValues
            />
        </span>
    )
}
