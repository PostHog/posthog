import { useValues } from 'kea'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelVizType } from '~/types'

import { funnelDataLogic } from './funnelDataLogic'

export function FunnelCardSummary(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { conversionMetrics, funnelVizType, hasPartialBreakdownSelection } = useValues(funnelDataLogic(insightProps))

    if (funnelVizType === FunnelVizType.Trends) {
        return null
    }

    return (
        <dl className="flex flex-wrap gap-x-4 gap-y-1 px-2 py-1 text-xs" data-attr="funnel-card-summary">
            {funnelVizType === FunnelVizType.Steps && (
                <div className="flex flex-wrap items-baseline gap-1">
                    <dt className="text-secondary">
                        {hasPartialBreakdownSelection ? 'Conversion of selected values' : 'Total conversion'}
                    </dt>
                    <dd className="m-0 font-semibold" translate="no">
                        {percentage(conversionMetrics.totalRate, 2, true)}
                    </dd>
                </div>
            )}
            {conversionMetrics.medianTime !== null && (
                <div className="flex flex-wrap items-baseline gap-1">
                    <dt className="text-secondary">
                        {hasPartialBreakdownSelection ? 'Median time (all breakdowns)' : 'Median time to convert'}
                    </dt>
                    <dd className="m-0 font-semibold" translate="no">
                        {humanFriendlyDuration(conversionMetrics.medianTime)}
                    </dd>
                </div>
            )}
        </dl>
    )
}
