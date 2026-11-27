import type { ExperimentWarehouseNativeExposureConfig } from '~/queries/schema/schema-general'

import { WarehouseNativeConnectionFields } from './WarehouseNativeConnectionFields'
import { WarehouseNativeQueryEditor } from './WarehouseNativeQueryEditor'

export type WarehouseNativeExposureFieldsProps = {
    exposure: ExperimentWarehouseNativeExposureConfig
    onChange: (exposure: ExperimentWarehouseNativeExposureConfig) => void
}

export function WarehouseNativeExposureFields({ exposure, onChange }: WarehouseNativeExposureFieldsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <WarehouseNativeConnectionFields
                binding={exposure}
                onChange={(binding) => onChange({ ...exposure, ...binding })}
            />
            <WarehouseNativeQueryEditor
                label="Exposure query"
                hint="Return one row per exposure with the columns entity_id, variant and timestamp. PostHog keeps the first exposure of each unit."
                query={exposure.query}
                onChange={(query) => onChange({ ...exposure, query })}
                data-attr="experiment-warehouse-native-exposure-query"
            />
        </div>
    )
}
