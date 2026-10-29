import clsx from 'clsx'
import { useMountedLogic } from 'kea'
import { useMemo } from 'react'

import { TileId } from 'scenes/web-analytics/common'
import { createPagePerformanceInsightProps } from 'scenes/web-analytics/pagePerformanceLogic'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { InsightVizNode } from '~/queries/schema/schema-general'

import { SearchAndAiQuery } from './SearchAndAiQuery'
import { SearchAndAiTrendHeader } from './SearchAndAiTrendHeader'

export function AiTrendCard({
    title,
    query,
    tileId,
    uniqueKey,
    scope,
    className,
}: {
    title: string
    query: InsightVizNode
    tileId: TileId
    uniqueKey: string
    scope?: string
    className?: string
}): JSX.Element {
    const logic = useMountedLogic(webAnalyticsLogic)
    const insightProps = useMemo(() => createPagePerformanceInsightProps(tileId, scope), [tileId, scope])
    return (
        <div className={clsx('min-h-88 min-w-0 flex flex-col', className)}>
            <SearchAndAiQuery
                uniqueKey={uniqueKey}
                query={query}
                insightProps={insightProps}
                renderQuery={(insightProps) => (
                    <WebQuery
                        attachTo={logic}
                        uniqueKey={uniqueKey}
                        query={query}
                        insightProps={insightProps}
                        tileId={tileId}
                        headerSlot={<SearchAndAiTrendHeader title={title} />}
                    />
                )}
            />
        </div>
    )
}
