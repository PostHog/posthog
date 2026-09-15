import { useActions, useValues } from 'kea'

import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export function SearchAndAiTrendHeader({ title }: { title: string }): JSX.Element {
    const {
        dateFilter: { interval },
    } = useValues(webAnalyticsLogic)
    const { setDateInterval } = useActions(webAnalyticsLogic)

    return (
        <PagePerformanceCardHeader
            title={title}
            actions={
                <div className="flex items-center gap-2">
                    <span className="text-secondary">Group by</span>
                    <IntervalFilterStandalone interval={interval} onIntervalChange={setDateInterval} />
                </div>
            }
        />
    )
}
