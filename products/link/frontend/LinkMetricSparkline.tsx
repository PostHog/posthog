import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'

import { linkMetricSparklineLogic } from './linkMetricSparklineLogic'

interface Props {
    id: string
}

export function LinkMetricSparkline({ id }: Props): JSX.Element {
    const logic = linkMetricSparklineLogic({ id })
    const { sparklineData, sparklineDataLoading } = useValues(logic)

    const displayData: SparklineTimeSeries[] = [
        {
            color: 'success',
            name: 'Clicks',
            values: sparklineData?.data || [],
        },
    ]

    return !sparklineData || sparklineDataLoading ? (
        <LemonSkeleton className="h-8 max-w-24" />
    ) : (
        <Sparkline
            loading={sparklineDataLoading}
            labels={sparklineData?.labels}
            data={displayData}
            className="h-8 max-w-24"
            maximumIndicator={false}
        />
    )
}
