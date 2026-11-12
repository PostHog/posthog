import { useState } from 'react'

import { LemonInput, LemonLabel, LemonSegmentedButton } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { metricSourcesToSeries, seriesToMetricSource } from 'scenes/experiments/metricQueryUtils'
import { commonActionFilterProps } from 'scenes/experiments/Metrics/Selectors'
import { quantileToPercentile } from 'scenes/experiments/MetricsView/shared/utils'
import { getPercentileError, MAX_PERCENTILE, MIN_PERCENTILE } from 'scenes/experiments/utils'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'

import { ExperimentQuantileMetric, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayCategory } from '~/types'

const PRESET_PERCENTILES = [50, 75, 90, 95, 99]

type PercentileOption = number | 'custom'

export function ExperimentQuantileMetricFields({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentQuantileMetric
    handleSetMetric: (newMetric: ExperimentQuantileMetric) => void
}): JSX.Element {
    const percentile = quantileToPercentile(metric.quantile)
    const [isCustom, setIsCustom] = useState(!PRESET_PERCENTILES.includes(percentile))
    const [customPercentile, setCustomPercentile] = useState<number | undefined>(percentile)
    const customPercentileError = isCustom ? getPercentileError(customPercentile) : undefined
    const eventName = metric.source.kind === NodeKind.EventsNode ? metric.source.event : null

    const setQuantileFromPercentile = (value: number): void => {
        handleSetMetric({ ...metric, quantile: Number((value / 100).toFixed(4)) })
    }

    return (
        <div className="space-y-4">
            <SeriesActionFilter
                bordered
                series={metricSourcesToSeries([metric.source])}
                trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                onChange={(series) => {
                    const source = seriesToMetricSource(series)
                    // Percentile metrics read event properties, so a warehouse table can't be a source
                    if (source && source.kind !== NodeKind.ExperimentDataWarehouseNode) {
                        handleSetMetric({
                            ...metric,
                            source: { ...source, math: undefined, math_property: metric.source.math_property },
                        })
                    }
                }}
                typeKey="experiment-metric-quantile"
                buttonCopy="Add event"
                showSeriesIndicator={false}
                hideRename={true}
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                {...commonActionFilterProps}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            />
            <div>
                <LemonLabel className="mb-1">Property</LemonLabel>
                <TaxonomicStringPopover
                    type="secondary"
                    groupType={TaxonomicFilterGroupType.NumericalEventProperties}
                    groupTypes={[TaxonomicFilterGroupType.NumericalEventProperties]}
                    value={metric.source.math_property}
                    onChange={(value) =>
                        handleSetMetric({ ...metric, source: { ...metric.source, math_property: value } })
                    }
                    eventNames={eventName ? [eventName] : []}
                    placeholder="Select a numeric property"
                    showNumericalPropsOnly
                    selectingKeyOnly
                    renderValue={(value) => (
                        <PropertyKeyInfo value={value} disablePopover type={TaxonomicFilterGroupType.EventProperties} />
                    )}
                    data-attr="experiment-quantile-property-select"
                />
                <div className="text-muted text-xs mt-1">
                    Events without a numeric value for this property don't count.
                </div>
            </div>
            <div>
                <LemonField.Pure label="Percentile" error={customPercentileError}>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSegmentedButton<PercentileOption>
                            size="small"
                            value={isCustom ? 'custom' : percentile}
                            onChange={(value) => {
                                if (value === 'custom') {
                                    setIsCustom(true)
                                    setCustomPercentile(percentile)
                                    return
                                }
                                setIsCustom(false)
                                setQuantileFromPercentile(value)
                            }}
                            options={[
                                ...PRESET_PERCENTILES.map((value) => ({
                                    value,
                                    label: `p${value}`,
                                    'data-attr': `experiment-quantile-p${value}`,
                                })),
                                { value: 'custom' as const, label: 'Custom' },
                            ]}
                        />
                        {isCustom && (
                            <LemonInput
                                type="number"
                                size="small"
                                min={MIN_PERCENTILE}
                                max={MAX_PERCENTILE}
                                step={0.1}
                                value={customPercentile}
                                status={customPercentileError ? 'danger' : 'default'}
                                onChange={(value) => {
                                    setCustomPercentile(value)
                                    // An invalid level still goes into the metric, so the save button reads the
                                    // metric and stays disabled until the level is valid.
                                    setQuantileFromPercentile(value ?? 0)
                                }}
                                prefix={<span className="text-muted">p</span>}
                                className="w-24"
                                data-attr="experiment-quantile-custom-percentile"
                            />
                        )}
                    </div>
                </LemonField.Pure>
                {!customPercentileError && (
                    <p className="text-muted text-xs mt-1 mb-0">{`p${percentile} is the value that ${percentile}% of events in a variant are at or below.`}</p>
                )}
            </div>
        </div>
    )
}
