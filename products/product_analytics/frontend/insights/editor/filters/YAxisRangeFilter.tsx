import { useActions, useValues } from 'kea'

import { BeginAtZeroOption } from 'lib/components/ChartOptions/BeginAtZeroOption'
import { ChartOptionNumberInput } from 'lib/components/ChartOptions/ChartOptionNumberInput'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function YAxisRangeFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter, yAxisScaleType, showPercentStackView } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const rangeDisabledReason =
        yAxisScaleType === 'log10'
            ? 'Not available on a logarithmic scale'
            : showPercentStackView
              ? 'Not available while showing percentages'
              : undefined
    // The minimum is hidden rather than cleared while the axis begins at zero, so the typed value
    // applies again when the toggle goes off.
    const beginsAtZero = trendsFilter?.yAxisStartAtZero !== false

    // An inverted pair sends the chart back to its automatic range, which otherwise just looks like
    // the controls not responding. Nothing to warn about while the minimum is disabled.
    const invalidRange =
        !beginsAtZero &&
        typeof trendsFilter?.yAxisMin === 'number' &&
        typeof trendsFilter?.yAxisMax === 'number' &&
        trendsFilter.yAxisMin >= trendsFilter.yAxisMax

    return (
        <div className="flex flex-col gap-2">
            <BeginAtZeroOption
                data-attr="trends-y-axis-start-at-zero"
                checked={beginsAtZero}
                disabledReason={rangeDisabledReason}
                onChange={(checked) => updateInsightFilter({ yAxisStartAtZero: checked ? undefined : false })}
            />
            {!beginsAtZero && (
                <ChartOptionNumberInput
                    label="Minimum"
                    data-attr="trends-y-axis-min-input"
                    value={trendsFilter?.yAxisMin}
                    placeholder="Auto"
                    disabledReason={rangeDisabledReason}
                    onChange={(yAxisMin) => updateInsightFilter({ yAxisMin })}
                />
            )}
            <ChartOptionNumberInput
                label="Maximum"
                data-attr="trends-y-axis-max-input"
                value={trendsFilter?.yAxisMax}
                placeholder="Auto"
                disabledReason={rangeDisabledReason}
                onChange={(yAxisMax) => updateInsightFilter({ yAxisMax })}
            />
            {invalidRange && <span className="text-xs text-danger">Maximum must be greater than minimum.</span>}
        </div>
    )
}
