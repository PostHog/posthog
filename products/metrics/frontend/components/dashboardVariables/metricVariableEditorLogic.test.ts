import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { metricsVariableOptionsCreate } from 'products/metrics/frontend/generated/api'

import { metricVariableEditorLogic } from './metricVariableEditorLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    metricsVariableOptionsCreate: jest.fn(),
}))

const mockOptions = metricsVariableOptionsCreate as jest.MockedFunction<typeof metricsVariableOptionsCreate>

describe('metricVariableEditorLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('sends a preview only after the one before it finishes', async () => {
        let finish: (value: { results: string[] }) => void = () => {}
        mockOptions.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)))
        mockOptions.mockResolvedValue({ results: ['b'] })
        const logic = metricVariableEditorLogic({
            dashboardId: 1,
            variables: [{ name: 'job', source: 'sql', query: 'SELECT job' }],
            options: {},
        })
        logic.mount()
        await new Promise((resolve) => setTimeout(resolve, 0))
        const sent = mockOptions.mock.calls.length

        logic.actions.loadPreview()
        logic.actions.loadPreview()
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(mockOptions).toHaveBeenCalledTimes(sent + 1)

        finish({ results: ['a'] })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockOptions).toHaveBeenCalledTimes(sent + 2)
        expect(logic.values.preview).toEqual(['b'])
    })
})
