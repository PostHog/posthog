import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import { LifecycleQuery } from '~/queries/schema/schema-general'

import { AggregationSelect } from 'products/product_analytics/frontend/insights/shared/AggregationSelect'
import { getAggregationTargetPronoun } from 'products/product_analytics/frontend/insights/shared/aggregationTargetUtils'

export function LifecycleSeriesHeader(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationGroupTypeIndex, querySource, hasDataWarehouseSeries } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { showGroupsOptions } = useValues(groupsModel)
    const showAggregationSelect = showGroupsOptions || hasDataWarehouseSeries
    const customAggregationTarget = (querySource as LifecycleQuery | null)?.customAggregationTarget === true
    const quillSurface = useQuillSurface()
    const pronoun = getAggregationTargetPronoun(aggregationGroupTypeIndex, customAggregationTarget)

    if (quillSurface) {
        return (
            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" render={<span className="m-0" />}>
                    Showing
                </Text>
                {showAggregationSelect ? (
                    <AggregationSelect className="min-w-0" insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                        Unique users
                    </Text>
                )}
                <Text size="xs" render={<span className="m-0" />}>
                    {`${pronoun} did`}
                </Text>
            </div>
        )
    }

    return (
        <div className="leading-6">
            <div className="flex items-center">
                Showing
                {showAggregationSelect ? (
                    <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <b> Unique users </b>
                )}
                {pronoun} did
            </div>
        </div>
    )
}
