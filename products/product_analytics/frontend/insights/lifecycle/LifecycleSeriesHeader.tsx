import { useValues } from 'kea'

import { AggregationSelect } from 'scenes/insights/filters/AggregationSelect'
import { getAggregationTargetPronoun } from 'scenes/insights/filters/aggregationTargetUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import { LifecycleQuery } from '~/queries/schema/schema-general'

export function LifecycleSeriesHeader(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationGroupTypeIndex, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { showGroupsOptions } = useValues(groupsModel)
    const showAggregationSelect = showGroupsOptions || hasDataWarehouseSeries
    const customAggregationTarget = (querySource as LifecycleQuery | null)?.customAggregationTarget === true

    return (
        <div className="leading-6">
            <div className="flex items-center">
                Showing
                {showAggregationSelect ? (
                    <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <b> Unique users </b>
                )}
                {getAggregationTargetPronoun(aggregationGroupTypeIndex, customAggregationTarget)} did
            </div>
        </div>
    )
}
