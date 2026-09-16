import { BindLogic, useActions, useValues } from 'kea'

import { PagePerformance } from 'scenes/web-analytics/PagePerformance'
import { PagePerformanceFilters } from 'scenes/web-analytics/PagePerformanceFilters'
import { pagePerformanceLogic } from 'scenes/web-analytics/pagePerformanceLogic'

import { pageVisibilityLogic } from './pageVisibilityLogic'

export const PageVisibility = (): JSX.Element => {
    const values = useValues(pageVisibilityLogic)
    const actions = useActions(pageVisibilityLogic)
    const controller = {
        dateFilter: values.dateFilter,
        compareFilter: values.compareFilter,
        conversionGoal: values.conversionGoal,
        filterTestAccounts: values.shouldFilterTestAccounts,
        isPathCleaningEnabled: values.isPathCleaningEnabled,
        webAnalyticsFilters: values.webAnalyticsFilters,
        rawWebAnalyticsFilters: values.rawWebAnalyticsFilters,
        domainFilter: values.domainFilter,
        deviceTypeFilter: values.deviceTypeFilter,
        countryFilter: values.countryFilter,
        referrerFilter: values.referrerFilter,
        ...actions,
    }

    return (
        <BindLogic logic={pagePerformanceLogic} props={{ source: 'marketing-analytics', filters: controller }}>
            <PagePerformanceFilters tabs={<></>} controller={controller} />
            <PagePerformance />
        </BindLogic>
    )
}
