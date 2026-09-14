import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonDivider, Popover } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isWebAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { WebAnalyticsDeviceToggle } from 'scenes/web-analytics/WebAnalyticsFilters'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import {
    WEB_ANALYTICS_PROPERTY_ALLOW_LIST,
    getWebAnalyticsTaxonomicGroupTypes,
} from 'scenes/web-analytics/WebPropertyFilters'

export function SearchAndAiFiltersPopover(): JSX.Element {
    const [visible, setVisible] = useState(false)
    const { rawWebAnalyticsFilters, deviceTypeFilter, preAggregatedEnabled, hasIncompatibleFilters } =
        useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="bottom-end"
            overlay={
                <div className="p-3 w-96 max-w-full space-y-3">
                    <div className="font-semibold">Property filters</div>
                    <PropertyFilters
                        disablePopover
                        propertyFilters={rawWebAnalyticsFilters}
                        onChange={(filters) => setWebAnalyticsFilters(filters.filter(isWebAnalyticsPropertyFilter))}
                        propertyAllowList={preAggregatedEnabled ? WEB_ANALYTICS_PROPERTY_ALLOW_LIST : undefined}
                        taxonomicGroupTypes={getWebAnalyticsTaxonomicGroupTypes(
                            preAggregatedEnabled ?? false,
                            !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2]
                        )}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                    />
                    <LemonDivider />
                    <div className="font-semibold">Device</div>
                    <WebAnalyticsDeviceToggle variant="select" />
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                tooltip={
                    hasIncompatibleFilters ? 'Some filters are not supported by the optimized query engine' : undefined
                }
                data-attr="show-web-analytics-filters"
                onClick={() => setVisible(!visible)}
                aria-expanded={visible}
                icon={
                    <IconWithCount count={rawWebAnalyticsFilters.length + (deviceTypeFilter ? 1 : 0)} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
            >
                Filters
            </LemonButton>
        </Popover>
    )
}
