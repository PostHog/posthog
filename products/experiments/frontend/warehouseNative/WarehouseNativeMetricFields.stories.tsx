import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import {
    type ExperimentMetric,
    ExperimentMetricType,
    ExperimentWarehouseNativeMathType,
    NodeKind,
} from '~/queries/schema/schema-general'

import { WarehouseNativeMetricFields } from './WarehouseNativeMetricFields'
import type { WarehouseNativeBinding } from './warehouseNativeSources'

const BINDING: WarehouseNativeBinding = {
    connection_id: '0190a3c5-0000-0000-0000-000000000001',
    unit: { unit_type: 'customer', id_namespace: 'billing_customer_id' },
}

const RATIO_METRIC: ExperimentMetric = {
    kind: NodeKind.ExperimentMetric,
    uuid: 'revenue-per-order',
    metric_type: ExperimentMetricType.RATIO,
    numerator: {
        kind: NodeKind.ExperimentWarehouseNativeNode,
        ...BINDING,
        query: 'SELECT customer_id AS entity_id, paid_at AS timestamp, amount\nFROM billing.payments',
        math: ExperimentWarehouseNativeMathType.Sum,
        math_property: 'amount',
    },
    denominator: {
        kind: NodeKind.ExperimentWarehouseNativeNode,
        ...BINDING,
        query: 'SELECT customer_id AS entity_id, created_at AS timestamp\nFROM billing.orders',
        math: ExperimentWarehouseNativeMathType.TotalCount,
    },
}

const meta: Meta<typeof WarehouseNativeMetricFields> = {
    title: 'Experiments/WarehouseNativeMetricFields',
    component: WarehouseNativeMetricFields,
    args: {
        metric: RATIO_METRIC,
        handleSetMetric: () => {},
        exposureBinding: null,
    },
    parameters: {
        testOptions: { waitForSelector: '.monaco-editor .view-line' },
    },
    decorators: [
        (Story) => (
            <div className="max-w-prose">
                <Story />
            </div>
        ),
        mswDecorator({
            get: {
                '/api/projects/:team_id/external_data_sources/connections/': [
                    {
                        id: BINDING.connection_id,
                        schema_name: null,
                        prefix: 'analytics',
                        engine: null,
                        source_type: 'BigQuery',
                        access_method: 'direct',
                        supports_hogql: false,
                        is_builtin_managed_warehouse: false,
                        description: 'Analytics warehouse',
                    },
                ],
                '/api/projects/:team_id/external_data_sources/direct_connection_options/': [],
            },
        }),
    ],
}
export default meta

export const SharedRatioMetric: StoryObj<typeof WarehouseNativeMetricFields> = {}
