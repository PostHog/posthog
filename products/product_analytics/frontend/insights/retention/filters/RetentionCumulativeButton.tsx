import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionCumulativeButton(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const cumulativeRetention = retentionFilter?.cumulative || false
    const is24HourWindow = retentionFilter?.timeWindowMode === '24_hour_windows'

    if (!canEditInsight) {
        return null
    }

    const value = !is24HourWindow && cumulativeRetention ? 1 : 0
    const onChange = (value: number): void => {
        updateInsightFilter({ cumulative: value === 1 })
    }
    const options = [
        {
            value: 0,
            label: 'on',
            tooltip: 'Retention value is the percentage of users who come back on a specific period',
        },
        {
            value: 1,
            label: 'on or after',
            disabledReason: is24HourWindow ? 'Cumulative retention is not supported for 24 hour windows' : undefined,
            tooltip: `
                    Retention value is the percentage of users who come back on a specific time period or any of the following time periods.
                    Also known as rolling, or unbounded retention.
                    For example, if a user comes back on day 7, they are counted in all previous retention periods.`,
        },
    ]

    if (quillSurface) {
        return (
            <ToggleGroup
                value={[String(value)]}
                onValueChange={(next: string[]) => {
                    if (next.length > 0) {
                        onChange(Number(next[0]))
                    }
                }}
            >
                {options.map((option) =>
                    option.disabledReason ? (
                        <ToggleGroupItem
                            key={option.value}
                            value={String(option.value)}
                            disabledReason={option.disabledReason}
                        >
                            {option.label}
                        </ToggleGroupItem>
                    ) : (
                        <Tooltip key={option.value}>
                            <TooltipTrigger render={<ToggleGroupItem value={String(option.value)} />}>
                                {option.label}
                            </TooltipTrigger>
                            <TooltipContent className="max-w-64">{option.tooltip}</TooltipContent>
                        </Tooltip>
                    )
                )}
            </ToggleGroup>
        )
    }

    return <LemonSegmentedButton value={value} onChange={onChange} options={options} />
}
