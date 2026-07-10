import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ResourceEditedEvent } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-external-1'
const LOADED_AT = '2026-05-01T00:00:00.000Z'
const NEWER = '2026-06-01T00:00:00.000Z'
const OLDER = '2026-04-01T00:00:00.000Z'

const makeWorkflow = (overrides: Partial<HogFlow> = {}): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'External edits test',
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
    updated_at: LOADED_AT,
    ...overrides,
})

const makeEvent = (overrides: Partial<ResourceEditedEvent> = {}): ResourceEditedEvent => ({
    notification_type: 'resource_edited',
    team_id: 1,
    resource_type: 'HogFlow',
    resource_id: WORKFLOW_ID,
    updated_at: NEWER,
    actor_user_id: 99,
    ...overrides,
})

describe('workflowLogic external edits', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let getCalls: number

    beforeEach(async () => {
        getCalls = 0
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    getCalls += 1
                    return [200, makeWorkflow()]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        resourceEditedLogic.mount()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        // The initial load counts as one GET; assertions below track edits beyond it.
        expect(getCalls).toBe(1)
    })

    afterEach(resumeKeaLoadersErrors)

    it('silently reconciles (sync + reload) when the local state is clean', async () => {
        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setSyncingExternalEdit', 'loadWorkflow', 'loadWorkflowSuccess'])

        // Reloaded from the server, no banner, and the syncing overlay clears on success.
        expect(getCalls).toBe(2)
        expect(logic.values.externallyEdited).toBe(false)
        expect(logic.values.isSyncingExternalEdit).toBe(false)
    })

    it('warns instead of clobbering when there are unsaved local edits', async () => {
        logic.actions.setAutoSaveEnabled(false)
        logic.actions.setWorkflowValue('name', 'My local edit')
        expect(logic.values.hasUnsavedChanges).toBe(true)

        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setExternallyEdited'])

        // Banner shown, no destructive reload, no syncing overlay.
        expect(logic.values.externallyEdited).toBe(true)
        expect(logic.values.isSyncingExternalEdit).toBe(false)
        expect(getCalls).toBe(1)
    })

    it.each([
        ['equal updated_at (our own save echo)', { updated_at: LOADED_AT }],
        ['older updated_at', { updated_at: OLDER }],
        ['a different workflow', { resource_id: 'some-other-workflow' }],
        ['a different resource type', { resource_type: 'EmailTemplate' }],
    ])('ignores %s', async (_label, overrides) => {
        resourceEditedLogic.actions.resourceEdited(makeEvent(overrides as Partial<ResourceEditedEvent>))
        // Give any (unexpected) async reaction a chance to run.
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(getCalls).toBe(1)
        expect(logic.values.externallyEdited).toBe(false)
        expect(logic.values.isSyncingExternalEdit).toBe(false)
    })

    it('clears the banner and reloads when the user chooses Reload', async () => {
        logic.actions.setAutoSaveEnabled(false)
        logic.actions.setWorkflowValue('name', 'My local edit')
        resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        await expectLogic(logic).toDispatchActions(['setExternallyEdited'])
        expect(logic.values.externallyEdited).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.loadWorkflow()
        }).toDispatchActions(['loadWorkflowSuccess'])

        expect(logic.values.externallyEdited).toBe(false)
    })

    it('adopts the latest server baseline (and keeps edits) when the user chooses Keep mine', async () => {
        logic.actions.setAutoSaveEnabled(false)
        logic.actions.setWorkflowValue('name', 'My local edit')
        resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        await expectLogic(logic).toDispatchActions(['setExternallyEdited'])
        expect(logic.values.externallyEdited).toBe(true)

        // The server copy has advanced; Keep mine adopts that timestamp so the user's next save wins.
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [200, makeWorkflow({ updated_at: NEWER })],
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.keepMyWorkflowVersion()
        }).toDispatchActions(['setSaveBaseUpdatedAt', 'setExternallyEdited'])

        expect(logic.values.externallyEdited).toBe(false)
        expect(logic.values.saveBaseUpdatedAt).toBe(NEWER)
        // The local edit is preserved — the canvas was not reloaded.
        expect(logic.values.workflow.name).toBe('My local edit')
    })

    it('shows the banner when a save is rejected as stale (409 backstop)', async () => {
        silenceKeaLoadersErrors() // the 409 save failure is the scenario under test
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [200, makeWorkflow()],
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': () => [409, { detail: 'stale_update' }],
            },
        })
        logic.actions.setAutoSaveEnabled(false)
        logic.actions.setWorkflowValue('name', 'Conflicting edit')

        await expectLogic(logic, () => {
            logic.actions.saveWorkflow(logic.values.workflow)
        }).toDispatchActions(['saveWorkflowFailure'])

        expect(logic.values.externallyEdited).toBe(true)
    })
})
