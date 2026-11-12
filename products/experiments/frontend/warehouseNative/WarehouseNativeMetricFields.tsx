import { type ExperimentMetric, ExperimentMetricType } from '~/queries/schema/schema-general'

import { WarehouseNativeConnectionFields } from './WarehouseNativeConnectionFields'
import { WarehouseNativeSourceFields } from './WarehouseNativeSourceFields'
import {
    type WarehouseNativeBinding,
    getWarehouseNativeBinding,
    toWarehouseNativeMetric,
} from './warehouseNativeSources'

export type WarehouseNativeMetricFieldsProps = {
    metric: ExperimentMetric
    handleSetMetric: (metric: ExperimentMetric) => void
    /**
     * The connection and the unit of the experiment's exposure. The metric must use the same, so the
     * form does not ask for them again. A shared metric has no experiment and asks for its own.
     */
    exposureBinding: WarehouseNativeBinding | null
}

export function WarehouseNativeMetricFields({
    metric,
    handleSetMetric,
    exposureBinding,
}: WarehouseNativeMetricFieldsProps): JSX.Element {
    const binding = exposureBinding ?? getWarehouseNativeBinding(metric)
    // Every edit passes through the binding, so no source can keep a connection the others do not have.
    const warehouseMetric = toWarehouseNativeMetric(metric, binding)

    return (
        <div className="flex flex-col gap-4">
            {exposureBinding ? (
                <div className="text-secondary text-sm">
                    The queries run on the connection of the experiment's exposure and return the same unit (
                    <span className="font-mono text-xs">
                        {exposureBinding.unit.unit_type} · {exposureBinding.unit.id_namespace}
                    </span>
                    ).
                </div>
            ) : (
                <WarehouseNativeConnectionFields
                    binding={binding}
                    onChange={(newBinding) => handleSetMetric(toWarehouseNativeMetric(metric, newBinding))}
                />
            )}
            {warehouseMetric.metric_type === ExperimentMetricType.RATIO ? (
                <>
                    <WarehouseNativeSourceFields
                        label="Numerator query"
                        source={warehouseMetric.numerator}
                        onChange={(numerator) => handleSetMetric({ ...warehouseMetric, numerator })}
                        data-attr="experiment-warehouse-native-numerator-query"
                    />
                    <WarehouseNativeSourceFields
                        label="Denominator query"
                        source={warehouseMetric.denominator}
                        onChange={(denominator) => handleSetMetric({ ...warehouseMetric, denominator })}
                        data-attr="experiment-warehouse-native-denominator-query"
                    />
                </>
            ) : (
                <WarehouseNativeSourceFields
                    label="Query"
                    source={warehouseMetric.source}
                    onChange={(source) => handleSetMetric({ ...warehouseMetric, source })}
                    data-attr="experiment-warehouse-native-metric-query"
                />
            )}
        </div>
    )
}
