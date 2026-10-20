import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function QuillRetentionCumulativeButton(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const cumulativeRetention = retentionFilter?.cumulative || false
    const is24HourWindow = retentionFilter?.timeWindowMode === '24_hour_windows'

    if (!canEditInsight) {
        return null
    }

    return (
        <ToggleGroup
            aria-label="When users return"
            value={[!is24HourWindow && cumulativeRetention ? 'on_or_after' : 'on']}
            onValueChange={(value: string[]) => {
                if (value[0]) {
                    updateInsightFilter({ cumulative: value[0] === 'on_or_after' })
                }
            }}
        >
            <Tooltip>
                <TooltipTrigger render={<ToggleGroupItem value="on" />}>on</TooltipTrigger>
                <TooltipContent className="max-w-80">
                    Retention value is the percentage of users who come back on a specific period
                </TooltipContent>
            </Tooltip>
            <Tooltip>
                <TooltipTrigger render={<ToggleGroupItem value="on_or_after" disabled={is24HourWindow} />}>
                    on or after
                </TooltipTrigger>
                <TooltipContent className="max-w-80">
                    {is24HourWindow
                        ? 'Cumulative retention is not supported for 24 hour windows'
                        : 'Retention value is the percentage of users who come back on a specific time period or any of the following time periods. Also known as rolling, or unbounded retention. For example, if a user comes back on day 7, they are counted in all previous retention periods.'}
                </TooltipContent>
            </Tooltip>
        </ToggleGroup>
    )
}
