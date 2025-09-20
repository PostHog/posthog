import { BindLogic, BuiltLogic, LogicWrapper, useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { GraphDataset } from '~/types'

import { revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { MRRBreakdownModal, mrrBreakdownModalLogic } from './modals'
import {
    RevenueAnalyticsLineGraph,
    TileProps,
    TileWrapper,
    extractLabelAndDatasets,
    goalLinesFromRevenueGoals,
} from './shared'

const MODE_OPTIONS: LemonSegmentedButtonOption<'mrr' | 'arr'>[] = [
    { value: 'mrr', label: 'MRR' },
    { value: 'arr', label: 'ARR' },
]

let uniqueNode = 0

export function RevenueAnalyticsMRRNode(props: {
    query: RevenueAnalyticsMRRQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `RevenueAnalyticsMRR.${uniqueNode++}`)

    const dataNodeLogicProps = {
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    }

    useAttachedLogic(insightLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(insightVizDataLogic(props.context.insightProps ?? {}), props.attachTo)
    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), props.attachTo)

    return (
        <BindLogic logic={insightLogic} props={props.context.insightProps ?? {}}>
            <BindLogic logic={insightVizDataLogic} props={props.context.insightProps ?? {}}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <Tile context={props.context} />
                </BindLogic>

                <MRRBreakdownModal />
            </BindLogic>
        </BindLogic>
    )
}

const Tile = ({ context }: TileProps): JSX.Element => {
    const { baseCurrency, breakdownProperties, revenueGoals, mrrMode } = useValues(revenueAnalyticsLogic)

    const logic = useMountedLogic(dataNodeLogic)
    const { response, responseLoading } = useValues(logic)
    const castResponse = response as RevenueAnalyticsMRRQueryResponse | null

    const { setMRRMode } = useActions(revenueAnalyticsLogic)
    const { openModal } = useActions(mrrBreakdownModalLogic)

    const { isPrefix, symbol: currencySymbol } = getCurrencySymbol(baseCurrency)

    const results = (castResponse?.results?.map((mrr) => mrr.total) as GraphDataset[]) ?? []

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

    const handleBreakdownClick = (): void => {
        if (castResponse) {
            openModal(castResponse.results)
        }
    }

    return (
        <TileWrapper
            context={context}
            title={mrrMode === 'mrr' ? 'MRR' : 'ARR'}
            tooltip="MRR is the total amount of recurring revenue generated from all sources, including all products and services in the last 30 days. ARR is that value multiplied by 12."
            extra={
                <div className="flex items-center gap-1 text-muted-alt">
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
                                  ? 'No MRR data available'
                                  : undefined
                        }
                    >
                        MRR Breakdown
                    </LemonButton>

                    <LemonSegmentedButton value={mrrMode} onChange={setMRRMode} options={MODE_OPTIONS} size="small" />
                </div>
            }
        >
            {() => (
                <RevenueAnalyticsLineGraph
                    data-attr="revenue-analytics-mrr-tile-graph"
                    datasets={mappedDatasets}
                    labels={labels}
                    legend={{
                        display: breakdownProperties.length > 0 && mappedDatasets.length > 1,
                        position: 'right',
                        // By default chart.js renders first item at the bottom of stack, but legend goes at the top, let's reverse the legend instead
                        reverse: true,
                    }}
                    trendsFilter={{
                        aggregationAxisFormat: 'numeric',
                        aggregationAxisPrefix: isPrefix ? currencySymbol : undefined,
                        aggregationAxisPostfix: isPrefix ? undefined : currencySymbol,
                        goalLines: goalLinesFromRevenueGoals(revenueGoals, 'mrr').map((goalLine) => ({
                            ...goalLine,
                            value: mrrMode === 'mrr' ? goalLine.value : goalLine.value * 12,
                        })),
                    }}
                />
            )}
        </TileWrapper>
    )
}
