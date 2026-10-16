import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isWebAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { DASHBOARD_FILTER_ALLOW_LIST, marketingDashboardLogic } from '../marketingDashboardLogic'

/** Filters on the same dimensions the dashboard can break down by, so a marketer can narrow to one
 * channel and keep every section in step. */
export function MarketingPropertyFilters(): JSX.Element {
    const { dashboardProperties } = useValues(marketingAnalyticsLogic)
    const { setDashboardProperties } = useActions(marketingAnalyticsLogic)
    // Mounted so the allow-list derived from the breakdown map is available.
    useValues(marketingDashboardLogic)
    const [open, setOpen] = useState(false)

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-end"
            className="max-w-200"
            overlay={
                <div className="p-3 w-96 max-w-[90vw]">
                    <PropertyFilters
                        disablePopover
                        propertyFilters={dashboardProperties}
                        onChange={(filters) => setDashboardProperties(filters.filter(isWebAnalyticsPropertyFilter))}
                        propertyAllowList={DASHBOARD_FILTER_ALLOW_LIST}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.SessionProperties]}
                        pageKey="marketing-dashboard"
                        eventNames={['$pageview']}
                    />
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={
                    <IconWithCount count={dashboardProperties.length} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
                onClick={() => setOpen(!open)}
                data-attr="marketing-dashboard-filters"
            >
                Filter
            </LemonButton>
        </Popover>
    )
}
