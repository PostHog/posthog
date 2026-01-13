import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'

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
            <LemonButtonWithDropdown
                size="small"
                type="secondary"
                dropdown={{
                    overlay: (
                        <div className="p-2 max-w-xs">
                            <p className="text-sm mb-2">
                                Querying all services can be slow for high-volume logs. Consider selecting specific
                                services for better performance.
                            </p>
                            <LemonButton
                                size="small"
                                type="primary"
                                fullWidth
                                onClick={() => setServiceNames([])}
                            >
                                Select specific services
                            </LemonButton>
                        </div>
                    ),
                    placement: 'bottom-start',
                }}
            >
                <span className="flex items-center gap-1">
                    <IconWarning className="text-warning" />
                    All services (slow)
                </span>
            </LemonButtonWithDropdown>
        )
    }

    return (
        <span className="rounded bg-surface-primary min-w-[150px] flex items-center gap-1">
            <PropertyValue
                size="small"
                endpoint={endpoint}
                operator={PropertyOperator.Exact}
                propertyKey="service_name"
                type={PropertyFilterType.Log}
                value={serviceNames}
                onSet={setServiceNames}
                placeholder="Select service"
                preloadValues
            />
            <LemonButton
                size="xsmall"
                type="tertiary"
                tooltip="Query all services (may be slow)"
                onClick={() => setServiceNames([ALL_SERVICES_VALUE])}
            >
                All
            </LemonButton>
        </span>
    )
}
