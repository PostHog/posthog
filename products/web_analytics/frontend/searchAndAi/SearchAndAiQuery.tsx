import { useActions, useValues } from 'kea'
import { ReactNode, useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import {
    buildDataTableTileDataNodeLogicProps,
    buildInsightVizTileDataNodeLogicProps,
} from 'scenes/web-analytics/tiles/skeletons/useTileSkeletonLoading'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { SearchAndAiLoading } from './SearchAndAiLoading'
import { searchAndAiQueryLogic } from './searchAndAiQueryLogic'

export function SearchAndAiQuery({
    query,
    insightProps,
    context,
    renderQuery,
    uniqueKey,
    footer,
    dataAttr,
    pending = false,
    header,
    resultsKey,
}: {
    query: DataTableNode | InsightVizNode
    insightProps: InsightLogicProps
    context?: QueryContext
    renderQuery?: (insightProps: InsightLogicProps) => ReactNode
    uniqueKey: string
    footer?: ReactNode
    dataAttr?: string
    pending?: boolean
    header?: ReactNode
    resultsKey?: string
}): JSX.Element {
    const dataNodeLogicProps = useMemo(
        () =>
            query.kind === NodeKind.DataTableNode
                ? buildDataTableTileDataNodeLogicProps({ query, insightProps, context: { ...context, insightProps } })
                : buildInsightVizTileDataNodeLogicProps({ query, insightProps }),
        [query, insightProps, context]
    )
    const logic = dataNodeLogic(dataNodeLogicProps)
    const { response, responseLoading, responseError, nextDataLoading } = useValues(logic)
    const { loadData } = useActions(logic)
    const { hasCurrentResponse, lastResponse } = useValues(searchAndAiQueryLogic({ dataNodeLogicProps, resultsKey }))
    const loading = responseLoading || (!hasCurrentResponse && !responseError)
    const initialLoading = loading && !hasCurrentResponse
    const showPreviousResults = hasCurrentResponse && (!!responseError || !response)
    const previousInsightProps: InsightLogicProps = useMemo(
        () => ({
            ...insightProps,
            dashboardItemId: `new-previous-${insightProps.dashboardItemId}`,
            doNotLoad: true,
            cachedInsight: {
                query,
                result: lastResponse && 'results' in lastResponse ? lastResponse.results : undefined,
            },
        }),
        [insightProps, query, lastResponse]
    )
    const liveContext = useMemo(() => ({ ...context, insightProps }), [context, insightProps])
    const previousContext = useMemo(
        () => ({ ...context, insightProps: previousInsightProps }),
        [context, previousInsightProps]
    )

    return (
        <SearchAndAiLoading
            className="SearchAndAiQuery"
            loading={loading || pending}
            label={!hasCurrentResponse ? 'Loading results' : nextDataLoading ? 'Loading more…' : 'Updating…'}
        >
            {header}
            {responseError && !responseLoading && (
                <LemonBanner
                    type="error"
                    className="m-3"
                    action={{
                        children: 'Try again',
                        onClick: () => loadData('force_async'),
                        loading: responseLoading,
                    }}
                >
                    {hasCurrentResponse
                        ? 'Could not update this section. Showing the previous results. Try again to refresh.'
                        : 'Could not load this section. Try again to reload.'}
                </LemonBanner>
            )}
            {initialLoading && <div className={query.kind === NodeKind.DataTableNode ? 'min-h-64' : 'min-h-88'} />}

            {showPreviousResults &&
                (renderQuery ? (
                    renderQuery(previousInsightProps)
                ) : (
                    <Query
                        query={query}
                        dataAttr={dataAttr}
                        cachedResults={lastResponse ?? undefined}
                        readOnly
                        context={previousContext}
                    />
                ))}
            <div
                className={
                    initialLoading || !!responseError || showPreviousResults ? 'hidden' : 'min-w-0 flex flex-col flex-1'
                }
            >
                {renderQuery ? (
                    renderQuery(insightProps)
                ) : (
                    <Query uniqueKey={uniqueKey} query={query} readOnly context={liveContext} dataAttr={dataAttr} />
                )}
            </div>
            {hasCurrentResponse && footer ? (
                <div className="border-t px-3 py-2 text-xs text-secondary">{footer}</div>
            ) : null}
        </SearchAndAiLoading>
    )
}
