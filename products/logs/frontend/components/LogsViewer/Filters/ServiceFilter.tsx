import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { projectLogic } from 'scenes/projectLogic'

import { LogsQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

export const ServiceFilter = (): JSX.Element => {
    const { filters } = useValues(logsViewerFiltersLogic)
    const { serviceNames, dateRange } = filters
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsViewerFiltersLogic)

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        attribute_type: 'resource',
        dateRange,
    }).url

    return (
        <span data-attr="logs-service-filter" className="rounded bg-surface-primary min-w-[150px] flex items-stretch">
            <PropertyValue
                size="small"
                endpoint={endpoint}
                operator={PropertyOperator.Exact}
                propertyKey="service_name"
                type={PropertyFilterType.Log}
                value={serviceNames}
                onSet={(value: LogsQuery['serviceNames']) => {
                    setServiceNames(value)
                }}
                placeholder="Service name"
                preloadValues
            />
        </span>
    )
}
