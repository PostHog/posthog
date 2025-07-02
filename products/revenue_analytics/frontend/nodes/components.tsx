import { LemonSegmentedButtonOption, Tooltip } from '@posthog/lemon-ui'

import { IconGraph, IconInfo, IconLineGraph } from '@posthog/icons'

import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { QueryContext } from '~/queries/types'
import { AnalyticsQueryResponseBase } from '~/queries/schema/schema-general'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { DisplayMode } from '../revenueAnalyticsLogic'

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
