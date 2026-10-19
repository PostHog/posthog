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

    it('publishes a selection without waiting for an unrelated slow query, and does not send that query again', async () => {
        let finishZone: (value: { results: string[] }) => void = () => {}
        const zone = new Promise<{ results: string[] }>((resolve) => {
            finishZone = resolve
        })
        mockOptions.mockImplementation(async (_team, body) => {
            if (body.query?.includes('zone')) {
                return zone
            }
            return { results: body.variables?.some((other) => other.values.includes('worker')) ? ['/b'] : ['/a'] }
        })
        const onSelectionsChange = jest.fn()
        const zoneVariable: MetricsDashboardVariable = {
            name: 'zone',
            source: 'sql',
            query: 'SELECT zone',
            current: { values: ['eu'] },
        }
        const logic = dashboardMetricVariablesLogic({
            dashboardId: 1,
            variables: [...variables, zoneVariable],
            onSelectionsChange,
        })
        logic.mount()
        await new Promise((resolve) => setTimeout(resolve, 0))

        logic.actions.select('service', { values: ['worker'] })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(onSelectionsChange).toHaveBeenCalledTimes(1)
        expect(mockOptions.mock.calls.filter(([, body]) => body.query === 'SELECT zone')).toHaveLength(1)
        finishZone({ results: ['eu'] })
        await expectLogic(logic).toFinishAllListeners()
    })
})
