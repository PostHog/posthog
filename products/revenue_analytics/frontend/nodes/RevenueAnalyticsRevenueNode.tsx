import { BindLogic, useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { useState } from 'react'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsRevenueQuery,
    RevenueAnalyticsRevenueQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { LemonButton, LemonSegmentedButton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import {
    DISPLAY_MODE_OPTIONS,
    extractLabelAndDatasets,
    RevenueAnalyticsLineGraph,
    TileProps,
    TileWrapper,
} from './shared'

let uniqueNode = 0
export function RevenueAnalyticsRevenueNode(props: {
    query: RevenueAnalyticsRevenueQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsRevenue.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading, queryId } = useValues(logic)

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
                <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                    <MRRTile
                        response={response as RevenueAnalyticsRevenueQueryResponse}
                        responseLoading={responseLoading}
                        queryId={queryId ?? ''}
                        context={props.context}
                    />
                    <GrossRevenueTile
                        response={response as RevenueAnalyticsRevenueQueryResponse}
                        responseLoading={responseLoading}
                        queryId={queryId ?? ''}
                        context={props.context}
                    />
                </BindLogic>
            </BindLogic>
        </div>
    )
}

const GROSS_REVENUE_TITLE = 'Gross Revenue'
const GROSS_REVENUE_TOOLTIP = (
    <span>
        Gross revenue is the total amount of revenue generated from all sources, including all products and services.
        <br />
        <br />
        We're automatically calculating deferred revenue which implies you might see revenue in the future if you've
        created an invoice item with a <code>period.start</code> and <code>period.end</code> that spans several months.
    </span>
)

const GrossRevenueTile = ({
    response,
    responseLoading,
    queryId,
    context,
}: TileProps<RevenueAnalyticsRevenueQueryResponse>): JSX.Element => {
    const { baseCurrency, revenueGoals, groupBy, insightsDisplayMode } = useValues(revenueAnalyticsLogic)
    const { setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const results = (response?.results?.gross as GraphDataset[]) ?? []
    const { labels, datasets } = extractLabelAndDatasets(results)

    return (
        <TileWrapper
            title={GROSS_REVENUE_TITLE}
            tooltip={GROSS_REVENUE_TOOLTIP}
            extra={
                <div className="flex items-center gap-1 text-muted-alt">
                    <LemonSegmentedButton
                        value={insightsDisplayMode}
                        onChange={setInsightsDisplayMode}
                        options={DISPLAY_MODE_OPTIONS}
                        size="small"
                    />
                </div>
            }
        >
            {responseLoading ? (
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
            ) : (
                <RevenueAnalyticsLineGraph
                    data-attr="revenue-analytics-revenue-tile-graph"
                    datasets={datasets}
                    labels={labels}
                    legend={{
                        display: groupBy.length > 0 && datasets.length > 1,
                        position: 'right',
                        // By default chart.js renders first item at the bottom of stack, but legend goes at the top, let's reverse the legend instead
                        reverse: true,
                    }}
                    trendsFilter={{
                        aggregationAxisFormat: 'numeric',
                        aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                        aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                        goalLines: revenueGoals.map((goal) => {
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
                        }),
                    }}
                />
            )}
        </TileWrapper>
    )
}

const MRRTile = ({
    response,
    responseLoading,
    queryId,
    context,
}: TileProps<RevenueAnalyticsRevenueQueryResponse>): JSX.Element => {
    const { baseCurrency, groupBy, mrrMode } = useValues(revenueAnalyticsLogic)
    const { setMRRMode } = useActions(revenueAnalyticsLogic)

    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const results = (response?.results?.mrr as GraphDataset[]) ?? []

    const { labels, datasets } = extractLabelAndDatasets(results)

    const mappedDatasets: GraphDataset[] = datasets.map((dataset) => ({
        ...dataset,
        data: dataset.data.map((value) => {
            if (typeof value !== 'number' || mrrMode === 'mrr') {
                return value
            }

            return value * 12
        }) as GraphDataset['data'], // Dumb type assertion because TS can't infer the type of the data
    }))

    return (
        <TileWrapper
            title={
                <>
                    <LemonButton
                        icon={<IconSwapHoriz />}
                        onClick={() => setMRRMode(mrrMode === 'mrr' ? 'arr' : 'mrr')}
                        tooltip={mrrMode === 'mrr' ? 'Switch to ARR' : 'Switch to MRR'}
                        type="secondary"
                        size="small"
                    >
                        <span className="font-semibold">{mrrMode === 'mrr' ? 'MRR' : 'ARR'}</span>
                    </LemonButton>
                </>
            }
            tooltip="MRR is the total amount of recurring revenue generated from all sources, including all products and services in the last 30 days. ARR is that value multiplied by 12."
            extra={
                <span className="flex items-center">
                    <AlphaTag />
                </span>
            }
        >
            {responseLoading ? (
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
            ) : (
                <RevenueAnalyticsLineGraph
                    data-attr="revenue-analytics-mrr-tile-graph"
                    datasets={mappedDatasets}
                    labels={labels}
                    legend={{
                        display: groupBy.length > 0 && mappedDatasets.length > 1,
                        position: 'right',
                        // By default chart.js renders first item at the bottom of stack, but legend goes at the top, let's reverse the legend instead
                        reverse: true,
                    }}
                    trendsFilter={{
                        aggregationAxisFormat: 'numeric',
                        aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                        aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                    }}
                />
            )}
        </TileWrapper>
    )
}

const AlphaTag = (): JSX.Element => {
    return (
        <Tooltip title="This is a new chart type that is still in alpha. Data might not be accurate.">
            <LemonTag type="completion" size="small">
                ALPHA
            </LemonTag>
        </Tooltip>
    )
}
