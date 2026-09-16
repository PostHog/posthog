import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

import { MarketingBreakdownSelect } from './MarketingBreakdownSelect'
import { MarketingPropertyFilters } from './MarketingPropertyFilters'
import { MarketingSectionSwitcher } from './MarketingSectionSwitcher'

export function MarketingDashboardHeader(): JSX.Element {
    const { dateFilter } = useValues(marketingAnalyticsLogic)
    const { setDates } = useActions(marketingAnalyticsLogic)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <SceneStickyBar showBorderBottom={false}>
                <div className="flex flex-wrap items-center gap-2">
                    <MarketingSectionSwitcher />
                    <div className="flex flex-wrap items-center gap-2 ml-auto">
                        <DateFilter
                            size="small"
                            dateFrom={dateFilter.dateFrom}
                            dateTo={dateFilter.dateTo}
                            onChange={setDates}
                            allowTimePrecision
                        />
                        <MarketingBreakdownSelect />
                        <MarketingPropertyFilters />
                        <ReloadAll iconOnly />
                    </div>
                </div>
            </SceneStickyBar>
        </BindLogic>
    )
}
