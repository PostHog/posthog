import { ReactNode } from 'react'

import { IconFlag } from '@posthog/icons'
import { Badge, Button, TableCell, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { FlattenedFunnelStepByBreakdown, FunnelStepWithConversionMetrics } from '~/types'

import { getSignificanceFromBreakdownStep } from '../shared/funnelStepTableUtils'
import { FunnelStepMetric } from './funnelStepsTableColumns'

interface QuillFunnelStepMetricCellProps {
    metric: FunnelStepMetric
    stepOrder: number
    breakdown: FlattenedFunnelStepByBreakdown
    onOpenPersons?: (series: FunnelStepWithConversionMetrics, converted: boolean) => void
    className?: string
}

function SignificantValue({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<Badge variant="warning" />}>
                <IconFlag />
                {children}
            </TooltipTrigger>
            <TooltipContent>Significantly different from other breakdown values</TooltipContent>
        </Tooltip>
    )
}

export function QuillFunnelStepMetricCell({
    metric,
    stepOrder,
    breakdown,
    onOpenPersons,
    className,
}: QuillFunnelStepMetricCellProps): JSX.Element {
    const series = breakdown.steps?.[stepOrder]
    const significance = getSignificanceFromBreakdownStep(breakdown, stepOrder)

    let content: ReactNode = null
    switch (metric) {
        case 'conversion':
        case 'dropoff': {
            if (!series) {
                break
            }
            const converted = metric === 'conversion'
            const count = humanFriendlyNumber((converted ? series.count : series.droppedOffFromPrevious) ?? 0)
            content = onOpenPersons ? (
                <Button
                    variant="link-foreground"
                    size="sm"
                    className="-mx-2"
                    onClick={() => onOpenPersons(series, converted)}
                >
                    {count}
                </Button>
            ) : (
                count
            )
            break
        }
        case 'conversion_so_far': {
            const rate = percentage(series?.conversionRates.total ?? 0, 2, true)
            content = significance?.total ? <SignificantValue>{rate}</SignificantValue> : rate
            break
        }
        case 'conversion_from_prev': {
            const rate = percentage(series?.conversionRates.fromPrevious ?? 0, 2, true)
            // Only flag as significant here if not flagged already in "Conversion so far"
            content =
                !significance?.total && significance?.fromPrevious ? <SignificantValue>{rate}</SignificantValue> : rate
            break
        }
        case 'median_time':
        case 'average_time': {
            const seconds = metric === 'median_time' ? series?.median_conversion_time : series?.average_conversion_time
            content = seconds != undefined ? humanFriendlyDuration(seconds, { maxUnits: 3 }) : '–'
            break
        }
    }

    return (
        <TableCell align="right" className={cn('whitespace-nowrap tabular-nums', className)}>
            {content}
        </TableCell>
    )
}
