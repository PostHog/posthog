import { expectLogic } from 'kea-test-utils'

import type { MetricsDashboardVariable } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsVariableOptionsCreate } from 'products/metrics/frontend/generated/api'

import { dashboardMetricVariablesLogic } from './dashboardMetricVariablesLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    metricsVariableOptionsCreate: jest.fn(),
}))

const mockOptions = metricsVariableOptionsCreate as jest.MockedFunction<typeof metricsVariableOptionsCreate>

const variables: MetricsDashboardVariable[] = [
    { name: 'service', source: 'custom', customValues: ['api', 'worker'], current: { values: ['api'] } },
    { name: 'route', source: 'sql', query: 'SELECT route WHERE service = $service', current: { values: ['/a'] } },
]

describe('dashboardMetricVariablesLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('publishes a parent selection once, with the selections of its dependents reconciled', async () => {
        mockOptions.mockResolvedValue({ results: ['/a'] })
        const onSelectionsChange = jest.fn()
        const logic = dashboardMetricVariablesLogic({ dashboardId: 1, variables, onSelectionsChange })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        mockOptions.mockResolvedValue({ results: ['/b'] })
        logic.actions.select('service', { values: ['worker'] })
        await expectLogic(logic).toFinishAllListeners()

        expect(onSelectionsChange).toHaveBeenCalledTimes(1)
        expect(
            onSelectionsChange.mock.calls[0][0].map((variable: MetricsDashboardVariable) => variable.current)
        ).toEqual([{ values: ['worker'] }, { values: ['/b'] }])
    })
})
