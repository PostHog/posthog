import { useMemo } from 'react'

import { TileId } from 'scenes/web-analytics/common'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'
import { createPagePerformanceInsightProps } from 'scenes/web-analytics/pagePerformanceLogic'
import { webAnalyticsDataTableQueryContext } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { SearchAndAiQuery } from './SearchAndAiQuery'

export function AiTableCard({
    title,
    query,
    tileId,
    columns,
    scope = 'table',
    tableLayout = 'fixed',
    footer,
}: {
    title: string
    query: DataTableNode
    tileId: TileId
    columns?: QueryContext['columns']
    scope?: string
    tableLayout?: 'auto' | 'fixed'
    footer?: React.ReactNode
}): JSX.Element {
    const context = useMemo(
        (): QueryContext => ({
            ...webAnalyticsDataTableQueryContext,
            ...(columns ? { columns: { ...webAnalyticsDataTableQueryContext.columns, ...columns } } : {}),
            insightProps: createPagePerformanceInsightProps(tileId, scope),
            showLoadNextButton: true,
            tableLayout,
            suppressSlowQuerySuggestions: true,
        }),
        [tileId, columns, scope, tableLayout]
    )
    return (
        <PagePerformanceCard className="flex-1 min-w-0" footer={footer}>
            <SearchAndAiQuery
                uniqueKey={scope === 'table' ? `page-performance-${tileId}` : `page-performance-${tileId}-${scope}`}
                query={query}
                insightProps={context.insightProps!}
                context={context}
                header={<PagePerformanceCardHeader title={title} />}
            />
        </PagePerformanceCard>
    )
}
