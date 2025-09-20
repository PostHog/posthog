import { useMountedLogic, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import {
    InsightEmptyState,
    InsightErrorState,
    InsightLoadingState,
    InsightTimeoutState,
    InsightValidationError,
} from 'scenes/insights/EmptyStates'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { LineGraph, LineGraphProps } from 'scenes/insights/views/LineGraph/LineGraph'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { extractValidationError, isTimeoutError } from '~/queries/nodes/InsightViz/utils'
import { AnyResponseType, GoalLine, RevenueAnalyticsGoal } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset, GraphType } from '~/types'

import { DisplayMode, revenueAnalyticsLogic } from '../revenueAnalyticsLogic'

// Simple interface for the tile props, letting us create tiles with a consistent interface
export interface TileProps {
    context: QueryContext
}

// Simple helper to extract the labels and datasets from the results we get from the server
export const extractLabelAndDatasets = (results: GraphDataset[]): { labels: string[]; datasets: GraphDataset[] } => {
    return {
        labels: results[0]?.labels ?? [],
        datasets: results.map((result, seriesIndex) => ({
            ...result,
            seriesIndex,
        })),
    }
}

// Helper to build goal lines from revenue goals
export const goalLinesFromRevenueGoals = (
    revenueGoals: RevenueAnalyticsGoal[],
    mode: RevenueAnalyticsGoal['mrr_or_gross']
): GoalLine[] => {
    return revenueGoals
        .filter((goal) => goal.mrr_or_gross === mode)
        .map((goal) => {
            const isFuture = dayjs(goal.due_date).isSameOrAfter(dayjs())

            return {
                label: `${goal.name} (${dayjs(goal.due_date).format('DD MMM YYYY')})`,
                value: goal.goal,
                displayLabel: true,
                borderColor: isFuture ? 'green' : 'red',

                // Only display smaller goals that are in the future
                // This implies that past goals that have been achieved already
                // will not be displayed
                displayIfCrossed: isFuture,
            }
        })
}

interface TileWrapperProps {
    context: QueryContext
    title: JSX.Element | string
    tooltip: JSX.Element | string
    extra?: JSX.Element
    children: (response: AnyResponseType) => JSX.Element
}

export const TileWrapper = ({
    title,
    tooltip,
    extra,
    children,
    context,
}: React.PropsWithChildren<TileWrapperProps>): JSX.Element => {
    const logic = useMountedLogic(dataNodeLogic)
    const { response, responseLoading, responseErrorObject, query, queryId } = useValues(logic)

    const validationError = extractValidationError(responseErrorObject)
    const timeoutError = isTimeoutError(responseErrorObject)

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        if (responseLoading) {
            return <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
        }

        if (validationError) {
            return <InsightValidationError query={query} detail={validationError} />
        }

        if (
            !responseErrorObject &&
            !responseLoading &&
            response &&
            'results' in response &&
            response.results.length === 0
        ) {
            return <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
        }

        if (responseErrorObject) {
            return <InsightErrorState query={query} queryId={queryId} />
        }

        if (timeoutError) {
            return <InsightTimeoutState queryId={queryId} />
        }

        return null
    })()

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between">
                <span className="text-lg font-semibold flex items-center gap-1">
                    {title}
                    <Tooltip title={tooltip}>
                        <IconInfo />
                    </Tooltip>
                </span>
                {extra}
            </div>

            <InsightsWrapper>
                <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                    {BlockingEmptyState ? BlockingEmptyState : children(response as AnyResponseType)}
                </div>
            </InsightsWrapper>
        </div>
    )
}

const DISPLAY_MODE_TO_GRAPH_TYPE: Record<DisplayMode, GraphType> = {
    line: GraphType.Line,
    area: GraphType.Line,
    bar: GraphType.Bar,

    // not really supported, but here to satisfy the type checker
    table: GraphType.Line,
}

// Simple wrapper around the LineGraph component, adding consistent display mode and date filter
export const RevenueAnalyticsLineGraph = (
    props: Omit<LineGraphProps, 'type' | 'isArea' | 'isInProgress' | 'labelGroupType'>
): JSX.Element => {
    const { insightsDisplayMode, dateFilter } = useValues(revenueAnalyticsLogic)

    return (
        <LineGraph
            type={DISPLAY_MODE_TO_GRAPH_TYPE[insightsDisplayMode]}
            isArea={insightsDisplayMode !== 'line'}
            isInProgress={!dateFilter.dateTo}
            legend={{ display: props.datasets.length > 1, position: 'right' }}
            trendsFilter={{ aggregationAxisFormat: 'numeric' }}
            labelGroupType="none"
            goalLines={props.goalLines || props.trendsFilter?.goalLines}
            {...props}
        />
    )
}
