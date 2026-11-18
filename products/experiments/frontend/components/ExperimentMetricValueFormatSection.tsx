import { useValues } from 'kea'
import posthog from 'posthog-js'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { isProportionMetric } from 'scenes/experiments/MetricsView/shared/utils'
import { teamLogic } from 'scenes/teamLogic'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { CurrencyCode, ExperimentMetric, ExperimentMetricValueFormatType } from '~/queries/schema/schema-general'

import { formatValueAs } from 'products/experiments/frontend/metricValueFormat'

/** `number` stands for a metric without a value format. */
export type ValueFormatOption = ExperimentMetricValueFormatType | 'number'

export const VALUE_FORMATS: { type: ExperimentMetricValueFormatType; label: string; example: number }[] = [
    { type: 'currency', label: 'Currency', example: 12.5 },
    { type: 'duration', label: 'Duration in seconds', example: 2431 },
    { type: 'duration_ms', label: 'Duration in milliseconds', example: 1500 },
    { type: 'percentage_scaled', label: 'Percentage from 0 to 1', example: 0.25 },
    { type: 'percentage', label: 'Percentage from 0 to 100', example: 25 },
]

function valueFormatOptions(baseCurrency: CurrencyCode): LemonSelectOption<ValueFormatOption>[] {
    return [
        { value: 'number', label: 'Number' },
        ...VALUE_FORMATS.map(({ type, label, example }) => {
            const fullLabel = type === 'currency' ? `${label} (${baseCurrency})` : label
            return {
                value: type,
                label: fullLabel,
                labelInMenu: (
                    <div className="flex flex-wrap items-center justify-between gap-x-4 w-full">
                        <span>{fullLabel}</span>
                        <span className="text-muted text-xs" translate="no">
                            {`${humanFriendlyNumber(example)} → ${formatValueAs(example, type, baseCurrency)}`}
                        </span>
                    </div>
                ),
            }
        }),
    ]
}

export const VALUE_FORMAT_DESCRIPTION =
    'Choose what kind of value this metric has. Results show it in that format. The calculation stays the same.'

/** Each value format with its label, and an example of a number before and after the format. */
export function valueFormatChoices(
    baseCurrency: CurrencyCode
): { value: ValueFormatOption; label: string; example?: string }[] {
    return [
        { value: 'number', label: 'Number' },
        ...VALUE_FORMATS.map(({ type, label, example }) => ({
            value: type,
            label: type === 'currency' ? `${label} (${baseCurrency})` : label,
            example: `${humanFriendlyNumber(example)} → ${formatValueAs(example, type, baseCurrency)}`,
        })),
    ]
}

export function useValueFormat(
    metric: ExperimentMetric,
    handleSetMetric: (newMetric: ExperimentMetric) => void
): {
    visible: boolean
    value: ValueFormatOption
    baseCurrency: CurrencyCode
    onChange: (option: ValueFormatOption) => void
} {
    const { baseCurrency } = useValues(teamLogic)
    const valueFormatEnabled = useFeatureFlag('EXPERIMENTS_METRIC_VALUE_FORMAT')

    return {
        // A proportion metric always shows a percentage. A metric that has a value format already keeps the
        // setting editable when the team is not flagged in.
        visible: !(isProportionMetric(metric) || (!valueFormatEnabled && metric.value_format == null)),
        value: metric.value_format?.type ?? 'number',
        baseCurrency,
        onChange: (option) => {
            handleSetMetric({ ...metric, value_format: option === 'number' ? undefined : { type: option } })
            posthog.capture('experiment metric value format changed', {
                value_format: option,
                metric_type: metric.metric_type,
            })
        },
    }
}

export function ExperimentMetricValueFormatSection({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element | null {
    const { visible, value, baseCurrency, onChange: handleValueFormatChange } = useValueFormat(metric, handleSetMetric)

    if (!visible) {
        return null
    }

    return (
        <>
            <SceneSection title="Value format" description={VALUE_FORMAT_DESCRIPTION} className="max-w-prose">
                <LemonSelect<ValueFormatOption>
                    data-attr="experiment-metric-value-format-select"
                    value={value}
                    onChange={handleValueFormatChange}
                    dropdownMatchSelectWidth={false}
                    options={valueFormatOptions(baseCurrency)}
                />
            </SceneSection>
            <SceneDivider />
        </>
    )
}
