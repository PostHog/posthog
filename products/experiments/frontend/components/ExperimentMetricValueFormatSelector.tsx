import { useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { CurrencyCode, ExperimentMetric, ExperimentMetricValueFormatType } from '~/queries/schema/schema-general'

import { formatValueAs } from 'products/experiments/frontend/metricValueFormat'

/** `number` stands for a metric without a value format. */
type ValueFormatOption = ExperimentMetricValueFormatType | 'number'

const FORMATS: { type: ExperimentMetricValueFormatType; label: string; example: number }[] = [
    { type: 'currency', label: 'Currency', example: 12.5 },
    { type: 'duration', label: 'Duration in seconds', example: 2431 },
    { type: 'duration_ms', label: 'Duration in milliseconds', example: 1500 },
    { type: 'percentage_scaled', label: 'Percentage from 0 to 1', example: 0.25 },
    { type: 'percentage', label: 'Percentage from 0 to 100', example: 25 },
]

function valueFormatOptions(baseCurrency: CurrencyCode): LemonSelectOption<ValueFormatOption>[] {
    return [
        { value: 'number', label: 'Number' },
        ...FORMATS.map(({ type, label, example }) => {
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

export function ExperimentMetricValueFormatSelector({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)

    const handleValueFormatChange = (option: ValueFormatOption): void => {
        handleSetMetric({ ...metric, value_format: option === 'number' ? undefined : { type: option } })
        posthog.capture('experiment metric value format changed', {
            value_format: option,
            metric_type: metric.metric_type,
        })
    }

    return (
        <SceneSection
            title="Value format"
            description="Choose what kind of value this metric has. Results show it in that format. The calculation stays the same."
            className="max-w-prose"
        >
            <LemonSelect<ValueFormatOption>
                data-attr="experiment-metric-value-format-select"
                value={metric.value_format?.type ?? 'number'}
                onChange={handleValueFormatChange}
                dropdownMatchSelectWidth={false}
                options={valueFormatOptions(baseCurrency)}
            />
        </SceneSection>
    )
}
