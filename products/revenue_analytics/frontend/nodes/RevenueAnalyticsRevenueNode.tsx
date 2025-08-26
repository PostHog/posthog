import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { IconSwapHoriz } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
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
import { MRRBreakdownModal, mrrBreakdownModalLogic } from './modals'
import {
    AlphaTag,
    DISPLAY_MODE_OPTIONS,
    RevenueAnalyticsLineGraph,
    TileProps,
    TileWrapper,
    extractLabelAndDatasets,
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
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <BindLogic logic={mrrBreakdownModalLogic} props={{}}>
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
                    <MRRBreakdownModal />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}

const GROSS_REVENUE_TITLE = 'Gross Revenue'
const GROSS_REVENUE_TOOLTIP = (
    <span>
        Gross revenue is the total amount of revenue generated from all sources, including all products and services.
        <br />
        <br />
        For Stripe sources, we're automatically calculating deferred revenue which implies you might see revenue in the
        future if you've created an invoice item with a <code>period.start</code> and <code>period.end</code> that spans
        several months.
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
    const { openModal } = useActions(mrrBreakdownModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const results = (response?.results?.mrr.map((mrr) => mrr.total) as GraphDataset[]) ?? []
    const { labels, datasets } = extractLabelAndDatasets(results)

    const handleBreakdownClick = (): void => {
        if (response) {
            openModal(response.results.mrr)
        }
    }

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
                <span className="flex items-center gap-2">
                    <AlphaTag />
                    {featureFlags[FEATURE_FLAGS.MRR_BREAKDOWN_REVENUE_ANALYTICS] && (
                        <LemonButton
                            icon={<IconGraph />}
                            onClick={handleBreakdownClick}
                            tooltip="View MRR breakdown"
                            type="secondary"
                            size="small"
                            disabledReason={
                                responseLoading
                                    ? 'Waiting for data...'
                                    : datasets.length === 0
                                      ? 'No data available'
                                      : undefined
                            }
                        >
                            MRR Breakdown
                        </LemonButton>
                    )}
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
