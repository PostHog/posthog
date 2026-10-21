import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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

    it('previews a query edit after an edit to another field', async () => {
        mockOptions.mockResolvedValue({ results: ['a'] })
        const logic = metricVariableEditorLogic({
            dashboardId: 1,
            variables: [{ name: 'job', source: 'sql', query: 'SELECT job' }],
            options: {},
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        mockOptions.mockClear()

        logic.actions.updateVariable(0, { query: 'SELECT other' })
        logic.actions.updateVariable(0, { label: 'Job' })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockOptions.mock.calls.map(([, body]) => body.query)).toEqual(['SELECT other'])
    })

    it('sends no preview for a query the editor rejects', async () => {
        mockOptions.mockResolvedValue({ results: ['a'] })
        const logic = metricVariableEditorLogic({
            dashboardId: 1,
            variables: [{ name: 'job', source: 'promql', query: 'up' }],
            options: {},
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockOptions).not.toHaveBeenCalled()
    })

    it('previews a query that refers to another variable in the draft', async () => {
        mockOptions.mockResolvedValue({ results: ['a'] })
        const logic = metricVariableEditorLogic({
            dashboardId: 1,
            variables: [
                { name: 'job', source: 'sql', query: 'SELECT $service' },
                { name: 'service', source: 'custom', customValues: ['api'] },
            ],
            options: {},
        })
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadPreview()).toFinishAllListeners()

        expect(mockOptions).toHaveBeenCalled()
    })

    it('shows a rejected preview without reporting it', async () => {
        mockOptions.mockRejectedValue({ status: 400, detail: 'Bad query private@example.com' })
        const captureException = jest.spyOn(posthog, 'captureException')
        const logic = metricVariableEditorLogic({
            dashboardId: 1,
            variables: [{ name: 'job', source: 'sql', query: 'SELECT job' }],
            options: {},
        })
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadPreview()).toFinishAllListeners()

        expect(logic.values.previewError).toEqual('Bad query private@example.com')
        expect(captureException).not.toHaveBeenCalled()
    })

    it('applies only after the server accepts each regex', async () => {
        mockOptions.mockImplementation(async (_team, body) => {
            if (body.regex === '(') {
                throw { status: 400, detail: 'The variable regex cannot be used: missing )' }
            }
            return { results: [] }
        })
        const onSave = jest.fn()
        const logic = metricVariableEditorLogic({
            dashboardId: 1,
            variables: [{ name: 'job', source: 'sql', query: 'SELECT job', regex: '(' }],
            options: {},
        })
        logic.mount()

        await expectLogic(logic, () => logic.actions.apply(onSave)).toFinishAllListeners()
        expect(onSave).not.toHaveBeenCalled()
        expect(logic.values.errors.job?.message).toContain('regex cannot be used')

        logic.actions.updateVariable(0, { regex: 'a(.*)' })
        await expectLogic(logic, () => logic.actions.apply(onSave)).toFinishAllListeners()
        expect(onSave).toHaveBeenCalledTimes(1)
    })

    it('checks a regex again after a failed check, and saves nothing once the editor closes', async () => {
        mockOptions.mockRejectedValueOnce({ status: 429, detail: 'Too many requests' })
        mockOptions.mockResolvedValue({ results: [] })
        const onSave = jest.fn()
        const logic = metricVariableEditorLogic({
            dashboardId: 1,
            variables: [{ name: 'job', source: 'sql', query: 'SELECT job', regex: 'a(.*)' }],
            options: {},
        })
        logic.mount()

        await expectLogic(logic, () => logic.actions.apply(onSave)).toFinishAllListeners()
        expect(onSave).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.apply(onSave)).toFinishAllListeners()
        expect(onSave).toHaveBeenCalledTimes(1)

        let pending: (value: { results: string[] }) => void = () => {}
        mockOptions.mockReturnValueOnce(new Promise((resolve) => (pending = resolve)))
        logic.actions.updateVariable(0, { regex: 'c(.*)' })
        logic.actions.apply(onSave)
        logic.actions.updateVariable(0, { regex: '(' })
        pending({ results: [] })
        await expectLogic(logic).toFinishAllListeners()
        expect(onSave).toHaveBeenCalledTimes(1)

        let finish: (value: { results: string[] }) => void = () => {}
        mockOptions.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)))
        logic.actions.updateVariable(0, { regex: 'b(.*)' })
        logic.actions.apply(onSave)
        logic.unmount()
        finish({ results: [] })
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(onSave).toHaveBeenCalledTimes(1)
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
