import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { WarehouseSyncWarningList } from '~/queries/nodes/DataNode/WarehouseSyncWarningList'
import { outOfDateSyncWarnings } from '~/queries/nodes/DataNode/warehouseSyncWarnings'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { InsightLogicProps } from '~/types'

import { QuillInsightBanner } from 'products/product_analytics/frontend/insights/shared/QuillInsightBanner'

export function InsightWarehouseSyncBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { response, responseLoading } = useValues(
        dataNodeLogic({ key: insightVizDataNodeKey(insightProps) } as DataNodeLogicProps)
    )
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const syncWarnings = outOfDateSyncWarnings(response && 'warnings' in response ? response.warnings : null)
    // While a new query runs, the response still belongs to the previous query.
    if (responseLoading || syncWarnings.length === 0) {
        return null
    }

    const message = (
        <>
            <span>Some warehouse tables this insight reads are out of date, so its results may not be current:</span>
            <WarehouseSyncWarningList warnings={syncWarnings} />
        </>
    )

    if (todayRailNav) {
        return (
            <QuillInsightBanner tone="warning" data-attr="insight-warehouse-sync-warnings">
                {message}
            </QuillInsightBanner>
        )
    }

    return (
        <LemonBanner type="warning" data-attr="insight-warehouse-sync-warnings">
            {message}
        </LemonBanner>
    )
}
