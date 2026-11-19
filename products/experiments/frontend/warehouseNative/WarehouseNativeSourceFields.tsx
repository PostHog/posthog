import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { ExperimentWarehouseNativeMathType, type ExperimentWarehouseNativeNode } from '~/queries/schema/schema-general'

import { WarehouseNativeQueryEditor } from './WarehouseNativeQueryEditor'

export type WarehouseNativeSourceFieldsProps = {
    label: string
    source: ExperimentWarehouseNativeNode
    onChange: (source: ExperimentWarehouseNativeNode) => void
    'data-attr'?: string
}

/** The query and the aggregation of one metric source. The metric owns the connection and the unit. */
export function WarehouseNativeSourceFields({
    label,
    source,
    onChange,
    'data-attr': dataAttr,
}: WarehouseNativeSourceFieldsProps): JSX.Element {
    const math = source.math ?? ExperimentWarehouseNativeMathType.TotalCount

    return (
        <div className="flex flex-col gap-3">
            <WarehouseNativeQueryEditor
                label={label}
                hint="Return one row per outcome with the columns entity_id and timestamp, plus any numeric column you want to sum."
                query={source.query}
                onChange={(query) => onChange({ ...source, query })}
                data-attr={dataAttr}
            />
            <div className="flex flex-wrap items-end gap-3">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Value per unit</LemonLabel>
                    <LemonSelect<ExperimentWarehouseNativeMathType>
                        value={math}
                        onChange={(newMath) =>
                            onChange({
                                ...source,
                                math: newMath,
                                math_property:
                                    newMath === ExperimentWarehouseNativeMathType.Sum
                                        ? source.math_property
                                        : undefined,
                            })
                        }
                        options={[
                            { value: ExperimentWarehouseNativeMathType.TotalCount, label: 'Count of rows' },
                            { value: ExperimentWarehouseNativeMathType.Sum, label: 'Sum of a column' },
                        ]}
                    />
                </div>
                {math === ExperimentWarehouseNativeMathType.Sum && (
                    <div className="flex min-w-40 flex-1 flex-col gap-1">
                        <LemonLabel>Column</LemonLabel>
                        <LemonInput
                            value={source.math_property ?? ''}
                            onChange={(column) => onChange({ ...source, math_property: column })}
                            placeholder="amount"
                        />
                    </div>
                )}
            </div>
        </div>
    )
}
