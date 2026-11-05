import { TodaySparkline } from 'scenes/project-homepage/today/TodaySparkline'

import type { MockTrend as MockTrendData } from './mockupData'

export function MockTrend({ trend }: { trend: MockTrendData }): JSX.Element {
    return (
        <figure className="InboxMockup__trend">
            <div className="InboxMockup__trendChart">
                <TodaySparkline values={trend.values} labels={trend.labels} tone="risk" emphasizeLast={4} />
            </div>
            <figcaption className="InboxMockup__muted">
                {trend.label}: <span className="InboxMockup__ink">{trend.value}</span>
            </figcaption>
        </figure>
    )
}
