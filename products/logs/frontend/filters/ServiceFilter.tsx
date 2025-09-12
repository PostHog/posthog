import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { projectLogic } from 'scenes/projectLogic'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { logsLogic } from '../logsLogic'

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange } = useValues(logsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsLogic)

    const endpoint = combineUrl(`api/environments/${currentProjectId}/logs/values`, {
        key: 'service.name',
        dateRange,
    }).url

    return (
        <span className="rounded bg-surface-primary min-w-[150px]">
            <PropertyValue
                size="small"
                endpoint={endpoint}
                operator={PropertyOperator.Exact}
                propertyKey="service_name"
                type={PropertyFilterType.Log}
                value={serviceNames}
                onSet={setServiceNames}
                placeholder="Service name"
                preloadValues
            />
        </span>
    )
}
