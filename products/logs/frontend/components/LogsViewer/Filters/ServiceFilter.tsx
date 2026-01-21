import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { projectLogic } from 'scenes/projectLogic'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { logsSceneLogic } from '../../../logsSceneLogic'

export const ServiceFilter = (): JSX.Element => {
    const { serviceNames, dateRange } = useValues(logsSceneLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { setServiceNames } = useActions(logsSceneLogic)

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
                onSet={setServiceNames}
                placeholder="Service name"
                preloadValues
            />
        </span>
    )
}
