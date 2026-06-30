import { useValues } from 'kea'

import { TooltipSurface } from '@posthog/quill-charts'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { funnelTooltipHeaderLabel, hasBreakdown } from 'scenes/funnels/funnelUtils'
import { formatBreakdownLabel, getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema/schema-general'
import { FunnelStepWithConversionMetrics } from '~/types'

export interface FunnelStepTooltipProps {
    showPersonsModal: boolean
    stepIndex: number
    series: FunnelStepWithConversionMetrics
    groupTypeLabel: string
    breakdownFilter: BreakdownFilter | null | undefined
    comparePeriodDateRange?: string | null
    aggregateConversionRate?: number | null
    /** True when the cursor is over the unfilled track area (drop-off region) rather than the bar. */
    isDropOffHover?: boolean
}

export function FunnelStepTooltip({
    showPersonsModal,
    stepIndex,
    series,
    groupTypeLabel,
    breakdownFilter,
    comparePeriodDateRange,
    aggregateConversionRate,
    isDropOffHover = false,
}: FunnelStepTooltipProps): JSX.Element {
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const eventName =
        getDisplayNameFromEntityFilter(getActionFilterFromFunnelStep(series)) ?? series.name ?? series.action_id

    const breakdownLabel = hasBreakdown(series.breakdown_value)
        ? formatBreakdownLabel(
              series.breakdown_value,
              breakdownFilter,
              allCohorts.results,
              formatPropertyValueForDisplay
          )
        : null

    const subLabel = funnelTooltipHeaderLabel({
        breakdownLabel: !series.compare_label || hasBreakdown(series.breakdown_value) ? breakdownLabel : null,
        compareLabel: series.compare_label,
        comparePeriodDateRange,
    })

    const showDropOff = isDropOffHover && stepIndex > 0

    const rows: { label: string; value: string }[] = showDropOff
        ? [
              { label: 'Dropped off', value: humanFriendlyNumber(series.droppedOffFromPrevious) },
              {
                  label: 'Drop-off from previous',
                  value: percentage(1 - series.conversionRates.fromPrevious, 2, true),
              },
              {
                  label: 'Drop-off from start',
                  value: percentage(1 - series.conversionRates.total, 2, true),
              },
          ]
        : [
              { label: stepIndex === 0 ? 'Entered' : 'Converted', value: humanFriendlyNumber(series.count) },
              ...(stepIndex > 0
                  ? [
                        {
                            label: 'Conversion from previous',
                            value: percentage(series.conversionRates.fromPrevious, 2, true),
                        },
                    ]
                  : []),
              { label: 'Conversion so far', value: percentage(series.conversionRates.total, 2, true) },
              ...(stepIndex > 0 && aggregateConversionRate != null
                  ? [{ label: 'Baseline conversion rate', value: percentage(aggregateConversionRate, 2, true) }]
                  : []),
              ...(stepIndex > 0 && series.median_conversion_time != null
                  ? [
                        {
                            label: 'Median time from previous',
                            value: humanFriendlyDuration(series.median_conversion_time, { maxUnits: 3 }),
                        },
                    ]
                  : []),
              ...(stepIndex > 0 && series.average_conversion_time != null
                  ? [
                        {
                            label: 'Average time from previous',
                            value: humanFriendlyDuration(series.average_conversion_time, { maxUnits: 3 }),
                        },
                    ]
                  : []),
          ]

    return (
        <TooltipSurface>
            <div className="font-semibold mb-0.5">
                Step {stepIndex + 1}: {eventName}
            </div>
            {subLabel && <div className="mb-1 text-xs opacity-50 truncate">{subLabel}</div>}
            <div>
                {rows.map(({ label, value }) => (
                    <div key={label} className="flex items-center gap-2 min-w-0 py-0.5">
                        <span className="flex-1 min-w-0 truncate opacity-75">{label}</span>
                        <strong>{value}</strong>
                    </div>
                ))}
            </div>
            {showPersonsModal && (
                <div className="mt-1 pt-1 border-t border-current/25 text-xs opacity-60 text-center">
                    Click to view {groupTypeLabel}
                </div>
            )}
        </TooltipSurface>
    )
}
