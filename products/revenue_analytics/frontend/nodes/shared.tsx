import { LemonSegmentedButtonOption, Tooltip } from '@posthog/lemon-ui'

import { IconGraph, IconInfo, IconLineGraph } from '@posthog/icons'

import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { QueryContext } from '~/queries/types'
import { AnalyticsQueryResponseBase } from '~/queries/schema/schema-general'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { DisplayMode, revenueAnalyticsLogic } from '../revenueAnalyticsLogic'
import { LineGraph, LineGraphProps } from 'scenes/insights/views/LineGraph/LineGraph'
import { useValues } from 'kea'
import { GraphType } from '~/types'

interface TileWrapperProps {
    title: JSX.Element | string
    tooltip: JSX.Element | string
    extra?: JSX.Element
}

export const TileWrapper = ({
    title,
    tooltip,
    extra,
    children,
}: React.PropsWithChildren<TileWrapperProps>): JSX.Element => {
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
                <div className="TrendsInsight TrendsInsight--ActionsLineGraph">{children}</div>
            </InsightsWrapper>
        </div>
    )
}

export interface TileProps<ResponseType extends AnalyticsQueryResponseBase<unknown>> {
    response: ResponseType
    responseLoading: boolean
    queryId: string
    context: QueryContext
}

export const DISPLAY_MODE_OPTIONS: LemonSegmentedButtonOption<DisplayMode>[] = [
    { value: 'line', icon: <IconLineGraph /> },
    { value: 'area', icon: <IconAreaChart /> },
    { value: 'bar', icon: <IconGraph /> },
]

const DISPLAY_MODE_TO_GRAPH_TYPE: Record<DisplayMode, GraphType> = {
    line: GraphType.Line,
    area: GraphType.Line,
    bar: GraphType.Bar,

    // not really supported, but here to satisfy the type checker
    table: GraphType.Line,
}
export const RevenueAnalyticsLineGraph = (
    props: Omit<LineGraphProps, 'type' | 'isArea' | 'isInProgress' | 'labelGroupType'>
): JSX.Element => {
    const { insightsDisplayMode, dateFilter } = useValues(revenueAnalyticsLogic)

    return (
        <LineGraph
            type={DISPLAY_MODE_TO_GRAPH_TYPE[insightsDisplayMode]}
            isArea={insightsDisplayMode !== 'line'}
            isInProgress={!dateFilter.dateTo}
            legend={{ display: true, position: 'right' }}
            trendsFilter={{ aggregationAxisFormat: 'numeric' }}
            labelGroupType="none"
            {...props}
        />
    )
}
