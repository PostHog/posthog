import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { type ExperimentWarehouseNativeExposureConfig, NodeKind } from '~/queries/schema/schema-general'

import { WarehouseNativeExposureFields } from './WarehouseNativeExposureFields'

const EXPOSURE: ExperimentWarehouseNativeExposureConfig = {
    kind: NodeKind.ExperimentWarehouseNativeExposureConfig,
    connection_id: '0190a3c5-0000-0000-0000-000000000001',
    unit: { unit_type: 'customer', id_namespace: 'billing_customer_id' },
    query: 'SELECT customer_id AS entity_id, variant, assigned_at AS timestamp\nFROM billing.experiment_assignments',
}

const meta: Meta<typeof WarehouseNativeExposureFields> = {
    title: 'Experiments/WarehouseNativeExposureFields',
    component: WarehouseNativeExposureFields,
    args: {
        exposure: EXPOSURE,
        onChange: () => {},
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
                        id: EXPOSURE.connection_id,
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

export const ExposureQuery: StoryObj<typeof WarehouseNativeExposureFields> = {}
