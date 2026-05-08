import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-autosave-1'

const makeWorkflow = (overrides: Partial<HogFlow> = {}): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'Autosave test',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
    ...overrides,
})

describe('workflowLogic auto-save', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let updateCalls: number
    const workflow = makeWorkflow()

    beforeEach(() => {
        updateCalls = 0
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': workflow,
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    updateCalls += 1
                    return [200, workflow]
                },
            },
        })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('debouncing existing workflow', () => {
        beforeEach(async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID, tabId: 'default' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        })

        it('collapses rapid edits into a single save after 3s', async () => {
            jest.useFakeTimers()

            logic.actions.setWorkflowValue('name', 'Edit 1')
            logic.actions.setWorkflowValue('name', 'Edit 2')
            logic.actions.setWorkflowValue('name', 'Edit 3')

            await jest.advanceTimersByTimeAsync(2000)
            expect(updateCalls).toBe(0)

            await jest.advanceTimersByTimeAsync(1500)
            await expectLogic(logic).toDispatchActions(['saveWorkflow', 'saveWorkflowSuccess'])
            expect(updateCalls).toBe(1)
        })

        it('updates lastSavedAt on auto-save success', async () => {
            jest.useFakeTimers()

            expect(logic.values.lastSavedAt).toBe('2026-05-01T00:00:00.000Z')

            logic.actions.setWorkflowValue('name', 'Edited')
            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])

            expect(logic.values.lastSavedAt).not.toBe('2026-05-01T00:00:00.000Z')
            expect(logic.values.lastSavedAt).not.toBeNull()
        })

        it('marks isAutoSave true on the auto-save path', async () => {
            jest.useFakeTimers()

            logic.actions.setWorkflowValue('name', 'Edited')
            await jest.advanceTimersByTimeAsync(3500)

            expect(logic.values.isAutoSave).toBe(true)
            expect(updateCalls).toBe(1)
        })
    })

    describe('skip cases', () => {
        it.each([
            ['new workflow', { id: 'new' as const }],
            ['template editing', { id: WORKFLOW_ID, editTemplateId: 'tpl-1' }],
        ])('does not auto-save for %s', async (_label, props) => {
            initKeaTests()
            logic = workflowLogic({ ...props, tabId: 'default' })
            logic.mount()

            jest.useFakeTimers()
            logic.actions.autoSaveWorkflow()
            await jest.advanceTimersByTimeAsync(3500)

            expect(updateCalls).toBe(0)
        })

        it('does not auto-save when there are validation errors', async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID, tabId: 'default' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            jest.useFakeTimers()

            logic.actions.setWorkflowValue('name', '')
            await jest.advanceTimersByTimeAsync(3500)

            expect(logic.values.workflowHasErrors).toBe(true)
            expect(updateCalls).toBe(0)
        })

        it('does not auto-save when nothing has changed', async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID, tabId: 'default' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            jest.useFakeTimers()
            logic.actions.autoSaveWorkflow()
            await jest.advanceTimersByTimeAsync(3500)

            expect(updateCalls).toBe(0)
        })
    })

    describe('auto-save toggle', () => {
        beforeEach(async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID, tabId: 'default' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        })

        it('does not auto-save when toggle is disabled', async () => {
            jest.useFakeTimers()

            logic.actions.setAutoSaveEnabled(false)
            logic.actions.setWorkflowValue('name', 'Edited')
            await jest.advanceTimersByTimeAsync(3500)

            expect(updateCalls).toBe(0)
        })

        it('resets isAutoSavePending when toggle is disabled', async () => {
            logic.actions.setWorkflowValue('name', 'Edited')
            expect(logic.values.isAutoSavePending).toBe(true)

            logic.actions.setAutoSaveEnabled(false)
            expect(logic.values.isAutoSavePending).toBe(false)
        })

        it('triggers auto-save when toggle is re-enabled with pending changes', async () => {
            jest.useFakeTimers()

            logic.actions.setAutoSaveEnabled(false)
            logic.actions.setWorkflowValue('name', 'Edited while off')
            await jest.advanceTimersByTimeAsync(3500)
            expect(updateCalls).toBe(0)

            logic.actions.setAutoSaveEnabled(true)
            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toDispatchActions(['saveWorkflow', 'saveWorkflowSuccess'])
            expect(updateCalls).toBe(1)
        })

        it('does not auto-save active workflows', async () => {
            jest.useFakeTimers()

            logic.actions.setWorkflowValue('status', 'active')
            logic.actions.setWorkflowValue('name', 'Edited active')
            await jest.advanceTimersByTimeAsync(3500)

            expect(updateCalls).toBe(0)
        })
    })

    describe('beforeUnmount', () => {
        it('flushes pending changes when the logic unmounts', async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID, tabId: 'default' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            logic.actions.setWorkflowValue('name', 'Unflushed edit')
            expect(logic.values.workflowChanged).toBe(true)

            logic.unmount()

            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(updateCalls).toBe(1)
        })

        it('does not flush when there are no changes', async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID, tabId: 'default' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            logic.unmount()
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(updateCalls).toBe(0)
        })
    })
})
