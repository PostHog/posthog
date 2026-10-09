import { IconPlusSmall, IconX } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem } from '@posthog/lemon-ui'

import { MetricAggregation, MetricRangeFunction, MetricsViewerClause } from './metricsViewerLogic'

interface OperationOption<T extends string> {
    value: T
    label: string
    description: string
}

const RANGE_FUNCTION_OPTIONS: OperationOption<MetricRangeFunction>[] = [
    {
        value: 'rate',
        label: 'Rate (/s)',
        description: 'Per-second rate of increase of each series. Use it for counters.',
    },
    {
        value: 'increase',
        label: 'Increase',
        description: 'Total increase of each series per time bucket. Use it for counters.',
    },
]

const AGGREGATION_OPTIONS: OperationOption<MetricAggregation>[] = [
    { value: 'sum', label: 'Sum', description: 'Add the series together.' },
    { value: 'avg', label: 'Average', description: 'Average of the series.' },
    { value: 'count', label: 'Series count', description: 'Number of series that reported.' },
    { value: 'min', label: 'Min', description: 'Lowest value across the series.' },
    { value: 'max', label: 'Max', description: 'Highest value across the series.' },
    { value: 'p95', label: 'p95', description: '95th percentile across the series.' },
]

function operationMenuItems<T extends string>(
    options: OperationOption<T>[],
    current: T | null,
    onPick: (value: T) => void
): LemonMenuItem[] {
    return options.map((option) => ({
        label: option.label,
        tooltip: option.description,
        active: option.value === current,
        onClick: () => onPick(option.value),
        'data-attr': `metrics-operation-option-${option.value}`,
    }))
}

function OperationChip<T extends string>({
    label,
    options,
    current,
    onPick,
    onRemove,
    removeTooltip,
    disabledReason,
    dataAttr,
}: {
    label: string
    options: OperationOption<T>[]
    current: T
    onPick: (value: T) => void
    onRemove: () => void
    removeTooltip: string
    disabledReason: string | null
    dataAttr: string
}): JSX.Element {
    return (
        <LemonMenu items={operationMenuItems(options, current, onPick)}>
            <LemonButton
                size="small"
                type="secondary"
                active
                disabledReason={disabledReason}
                sideAction={{
                    icon: <IconX />,
                    onClick: onRemove,
                    tooltip: removeTooltip,
                    'data-attr': `${dataAttr}-remove`,
                }}
                data-attr={dataAttr}
            >
                {label}
            </LemonButton>
        </LemonMenu>
    )
}

/** The operations applied to a clause's series, in the order they run: a range function on each
 * series first, then an aggregation across series. Mirrors the operation chips of a PromQL builder. */
export function MetricsOperations({
    clause,
    onRangeFunctionChange,
    onAggregationChange,
    disabledReason,
}: {
    clause: Pick<MetricsViewerClause, 'rangeFunction' | 'aggregation'>
    onRangeFunctionChange: (rangeFunction: MetricRangeFunction | null) => void
    onAggregationChange: (aggregation: MetricAggregation | null) => void
    disabledReason: string | null
}): JSX.Element {
    const { rangeFunction, aggregation } = clause
    const rangeFunctionOption = RANGE_FUNCTION_OPTIONS.find((option) => option.value === rangeFunction)
    const aggregationOption = AGGREGATION_OPTIONS.find((option) => option.value === aggregation)

    return (
        <div className="flex flex-wrap items-center gap-1" data-attr="metrics-operations">
            {rangeFunctionOption && (
                <OperationChip
                    label={rangeFunctionOption.label}
                    options={RANGE_FUNCTION_OPTIONS}
                    current={rangeFunctionOption.value}
                    onPick={onRangeFunctionChange}
                    onRemove={() => onRangeFunctionChange(null)}
                    removeTooltip="Remove range function"
                    disabledReason={disabledReason}
                    dataAttr="metrics-operation-range-function"
                />
            )}
            {aggregationOption && (
                <OperationChip
                    label={aggregationOption.label}
                    options={AGGREGATION_OPTIONS}
                    current={aggregationOption.value}
                    onPick={onAggregationChange}
                    onRemove={() => onAggregationChange(null)}
                    removeTooltip="Remove aggregation"
                    disabledReason={disabledReason}
                    dataAttr="metrics-operation-aggregation"
                />
            )}
            <LemonMenu
                items={[
                    {
                        title: 'Range functions',
                        items: operationMenuItems(RANGE_FUNCTION_OPTIONS, rangeFunction, onRangeFunctionChange),
                    },
                    {
                        title: 'Aggregations',
                        items: operationMenuItems(AGGREGATION_OPTIONS, aggregation, onAggregationChange),
                    },
                ]}
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlusSmall />}
                    disabledReason={disabledReason}
                    tooltip="Add an operation. Without an aggregation, each series gets its own line."
                    data-attr="metrics-operation-add"
                >
                    Operation
                </LemonButton>
            </LemonMenu>
        </div>
    )
}
