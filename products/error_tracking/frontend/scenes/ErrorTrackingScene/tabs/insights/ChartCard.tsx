import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { InsightsTrackableItem } from './errorTrackingInsightsLogic'
import { insightNewUrl } from './queries'

export function ChartCard({
    title,
    description,
    query,
    chartKey,
    loadStartTime,
    onLoad,
}: {
    title: string
    description: string
    query: InsightVizNode<TrendsQuery>
    chartKey: InsightsTrackableItem
    loadStartTime: number
    onLoad: (item: InsightsTrackableItem, durationMs: number) => void
}): JSX.Element {
    const insightProps: InsightLogicProps = {
        dashboardItemId: `new-AdHoc.error-tracking-insights-${chartKey}`,
        dataNodeCollectionId: `error-tracking-insights-${chartKey}`,
        query,
        onData: () => onLoad(chartKey, Math.round(performance.now() - loadStartTime)),
    }

    return (
        <div className="border rounded-lg bg-surface-primary flex flex-col h-100">
            <div className="flex items-center justify-between px-4 pt-3 pb-1 shrink-0">
                <div>
                    <h3 className="font-semibold text-sm m-0">{title}</h3>
                    <p className="text-xs text-secondary m-0">{description}</p>
                </div>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconExternal />}
                    to={insightNewUrl(query)}
                    targetBlank
                >
                    Open as insight
                </LemonButton>
            </div>
            <div className="ErrorTracking__insights flex-1 min-h-0 p-2">
                <Query query={query} readOnly={true} context={{ insightProps }} />
            </div>
        </div>
    )
}
