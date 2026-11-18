import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    METRIC_CONTEXTS,
    experimentMetricModalLogic,
} from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'

import { MetricSourceModal } from './MetricSourceModal'
import { metricSourceModalLogic } from './metricSourceModalLogic'

describe('MetricSourceModal', () => {
    beforeEach(() => {
        initKeaTests()
        metricSourceModalLogic.mount()
        experimentMetricModalLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('starts a warehouse-native metric when the experiment it is given has a warehouse-native exposure', async () => {
        const unit = { unit_type: 'customer', id_namespace: 'billing_customer_id' }
        // The wizard draft lives outside experimentLogic, so the modal must read the experiment it is given
        render(
            <MetricSourceModal
                experiment={{
                    metrics: [],
                    metrics_secondary: [],
                    start_date: undefined,
                    exposure_criteria: {
                        exposure_config: {
                            kind: NodeKind.ExperimentWarehouseNativeExposureConfig,
                            connection_id: 'connection-1',
                            unit,
                            query: 'SELECT customer_id AS entity_id, variant, assigned_at AS timestamp FROM billing.assignments',
                        },
                    },
                }}
            />
        )
        metricSourceModalLogic.actions.openMetricSourceModal(METRIC_CONTEXTS.primary)

        await userEvent.click(await screen.findByText('Single-use'))

        expect(experimentMetricModalLogic.values.metric).toMatchObject({
            metric_type: ExperimentMetricType.MEAN,
            source: { kind: NodeKind.ExperimentWarehouseNativeNode, connection_id: 'connection-1', unit, query: '' },
        })
    })
})
