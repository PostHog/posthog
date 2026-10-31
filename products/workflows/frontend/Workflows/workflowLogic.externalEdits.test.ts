import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ResourceEditedEvent } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { HogFlow, HogFlowAction } from './hogflows/types'
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
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: LOADED_AT,
    ...overrides,
})

const emailStep = (id: string, subject: string): HogFlowAction => ({
    id,
    type: 'function_email',
    name: id,
    description: '',
    created_at: 0,
    updated_at: 0,
    config: { template_id: 'template-email', inputs: { email: { value: { subject } } } },
})

const withSubject = (action: HogFlowAction, subject: string): HogFlowAction => emailStep(action.id, subject)

const withEmailSteps = (subjects: { welcome: string; followUp: string }, overrides: Partial<HogFlow> = {}): HogFlow =>
    makeWorkflow({
        actions: [
            ...makeWorkflow().actions,
            emailStep('welcome', subjects.welcome),
            emailStep('follow_up', subjects.followUp),
        ],
        ...overrides,
    })

const chain = (...ids: string[]): HogFlow['edges'] =>
    ids.slice(1).map((to, index) => ({ from: ids[index], to, type: 'continue' as const }))

const withChainedSteps = (
    stepIds: string[],
    subject: (id: string) => string,
    overrides: Partial<HogFlow> = {}
): HogFlow =>
    makeWorkflow({
        actions: [...makeWorkflow().actions, ...stepIds.map((id) => emailStep(id, subject(id)))],
        edges: chain('trigger_node', ...stepIds, 'exit_node'),
        ...overrides,
    })

const danglingEdges = (workflow: HogFlow): HogFlow['edges'] => {
    const stepIds = new Set(workflow.actions.map((action) => action.id))
    return workflow.edges.filter((edge) => !stepIds.has(edge.from) || !stepIds.has(edge.to))
}

const subjectOf = (workflow: HogFlow, actionId: string): string | undefined =>
    (workflow.actions.find((action) => action.id === actionId)?.config as Record<string, any> | undefined)?.inputs
        ?.email?.value?.subject

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
    let savedBodies: Record<string, any>[]

    const useWorkflowMock = (workflow: HogFlow): void => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    getCalls += 1
                    return [200, workflow]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    savedBodies.push(body)
                    return [200, { ...workflow, ...body }]
                },
            },
        })
    }

    beforeEach(async () => {
        getCalls = 0
        savedBodies = []
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
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_KEEP_LOCAL_EDITS], {
            [FEATURE_FLAGS.WORKFLOWS_KEEP_LOCAL_EDITS]: true,
        })
        resourceEditedLogic.mount()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        // The initial load counts as one GET; assertions below track edits beyond it.
        expect(getCalls).toBe(1)
    })

    afterEach(() => {
        jest.useRealTimers()
        resumeKeaLoadersErrors()
    })

    const reconcileExternalEdit = async (): Promise<void> => {
        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setSyncingExternalEdit', 'loadWorkflow', 'loadWorkflowSuccess'])
    }

    const flushAutoSave = async (): Promise<Record<string, any>> => {
        await jest.advanceTimersByTimeAsync(3500)
        await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])
        expect(savedBodies).toHaveLength(1)
        return savedBodies[0]
    }

    it('silently reconciles (sync + reload) when the local state is clean', async () => {
        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setSyncingExternalEdit', 'loadWorkflow', 'loadWorkflowSuccess'])

        // Reloaded from the server, no banner, and the syncing overlay clears on success.
        expect(getCalls).toBe(2)
        expect(logic.values.externallyEdited).toBe(false)
        expect(logic.values.isSyncingExternalEdit).toBe(false)
    })

    it.each([
        {
            label: 'another email step',
            server: { welcome: 'Welcome', followUp: 'Follow-up rewritten elsewhere' },
            expected: { welcome: 'Welcome, typed here', followUp: 'Follow-up rewritten elsewhere' },
        },
        {
            label: 'the email step being typed in',
            server: { welcome: 'Welcome rewritten elsewhere', followUp: 'Follow-up' },
            expected: { welcome: 'Welcome, typed here', followUp: 'Follow-up' },
        },
    ])('keeps the email being typed in when an external edit changes $label', async ({ server, expected }) => {
        useWorkflowMock(withEmailSteps({ welcome: 'Welcome', followUp: 'Follow-up' }))
        logic.actions.loadWorkflow()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        const welcome = logic.values.workflow.actions.find((action) => action.id === 'welcome')!
        logic.actions.setWorkflowActionConfig('welcome', withSubject(welcome, 'Welcome, typed here').config)
        useWorkflowMock(withEmailSteps(server, { updated_at: NEWER }))
        jest.useFakeTimers()

        await reconcileExternalEdit()

        expect(logic.values.externallyEdited).toBe(false)
        expect({
            welcome: subjectOf(logic.values.workflow, 'welcome'),
            followUp: subjectOf(logic.values.workflow, 'follow_up'),
        }).toEqual(expected)

        const saved = await flushAutoSave()
        expect(saved.base_updated_at).toBe(NEWER)
        expect({
            welcome: subjectOf(saved as HogFlow, 'welcome'),
            followUp: subjectOf(saved as HogFlow, 'follow_up'),
        }).toEqual(expected)
    })

    it.each([
        {
            label: 'the user typed into the step the server deleted',
            editLocally: (l: ReturnType<typeof workflowLogic.build>): void => {
                const welcome = l.values.workflow.actions.find((action) => action.id === 'welcome')!
                l.actions.setWorkflowActionConfig('welcome', withSubject(welcome, 'Welcome, typed here').config)
            },
            server: withChainedSteps(['follow_up'], () => 'Follow-up rewritten elsewhere', { updated_at: NEWER }),
            expectedEdges: chain('trigger_node', 'welcome', 'follow_up', 'exit_node'),
            expectedSubjects: { welcome: 'Welcome, typed here', followUp: 'Follow-up rewritten elsewhere' },
        },
        {
            label: 'the user reordered steps while the server deleted one',
            editLocally: (l: ReturnType<typeof workflowLogic.build>): void => {
                l.actions.setWorkflowValue('edges', chain('trigger_node', 'follow_up', 'welcome', 'exit_node'))
            },
            server: withChainedSteps(['welcome'], () => 'Welcome', { updated_at: NEWER }),
            expectedEdges: chain('trigger_node', 'follow_up', 'welcome', 'exit_node'),
            expectedSubjects: { welcome: 'Welcome', followUp: 'Follow-up' },
        },
        {
            label: 'the user added a step after an email the server rewrote',
            editLocally: (l: ReturnType<typeof workflowLogic.build>): void => {
                l.actions.setWorkflowValues({
                    actions: [...l.values.workflow.actions, emailStep('reminder', 'Reminder')],
                    edges: chain('trigger_node', 'welcome', 'reminder', 'follow_up', 'exit_node'),
                })
            },
            server: withChainedSteps(
                ['welcome', 'follow_up'],
                (id) => (id === 'welcome' ? 'Welcome rewritten elsewhere' : 'Follow-up'),
                { updated_at: NEWER }
            ),
            expectedEdges: chain('trigger_node', 'welcome', 'reminder', 'follow_up', 'exit_node'),
            expectedSubjects: { welcome: 'Welcome rewritten elsewhere', followUp: 'Follow-up' },
        },
    ])('saves a connected graph when $label', async ({ editLocally, server, expectedEdges, expectedSubjects }) => {
        useWorkflowMock(
            withChainedSteps(['welcome', 'follow_up'], (id) => (id === 'welcome' ? 'Welcome' : 'Follow-up'))
        )
        logic.actions.loadWorkflow()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        editLocally(logic)
        useWorkflowMock(server)
        jest.useFakeTimers()

        await reconcileExternalEdit()

        const saved = (await flushAutoSave()) as HogFlow
        expect(saved.edges).toEqual(expectedEdges)
        expect(danglingEdges(saved)).toEqual([])
        expect({ welcome: subjectOf(saved, 'welcome'), followUp: subjectOf(saved, 'follow_up') }).toEqual(
            expectedSubjects
        )
    })

    describe('branch conditions', () => {
        const branch = (conditions: string[]): HogFlowAction =>
            ({
                id: 'branch',
                type: 'conditional_branch',
                name: 'branch',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: { conditions: conditions.map((filters) => ({ filters })) },
            }) as unknown as HogFlowAction
        const branchEdges: HogFlow['edges'] = [
            { from: 'trigger_node', to: 'branch', type: 'continue' },
            { from: 'branch', to: 'welcome', type: 'branch', index: 0 },
            { from: 'branch', to: 'follow_up', type: 'branch', index: 1 },
            { from: 'branch', to: 'exit_node', type: 'continue' },
            { from: 'welcome', to: 'exit_node', type: 'continue' },
            { from: 'follow_up', to: 'exit_node', type: 'continue' },
        ]
        const withReminderEdges: HogFlow['edges'] = [
            ...branchEdges.filter((edge) => edge.from !== 'follow_up'),
            { from: 'follow_up', to: 'reminder', type: 'continue' },
            { from: 'reminder', to: 'exit_node', type: 'continue' },
        ]

        it.each([
            {
                label: 'adds a step',
                editLocally: (l: ReturnType<typeof workflowLogic.build>): void => {
                    l.actions.setWorkflowValues({
                        actions: [...l.values.workflow.actions, emailStep('reminder', 'Reminder')],
                        edges: withReminderEdges,
                    })
                },
                expectedConditions: ['vip', 'trial'],
                expectedEdges: withReminderEdges,
            },
            {
                label: 'edits a condition',
                editLocally: (l: ReturnType<typeof workflowLogic.build>): void => {
                    l.actions.setWorkflowActionConfig('branch', branch(['vip customers', 'trial']).config)
                },
                expectedConditions: ['vip customers', 'trial'],
                expectedEdges: branchEdges,
            },
        ])(
            'keeps them matched to their edges when the user $label while the server removes one',
            async ({ editLocally, expectedConditions, expectedEdges }) => {
                useWorkflowMock(
                    makeWorkflow({
                        actions: [
                            ...makeWorkflow().actions,
                            branch(['vip', 'trial']),
                            emailStep('welcome', 'Welcome'),
                            emailStep('follow_up', 'Follow-up'),
                        ],
                        edges: branchEdges,
                    })
                )
                logic.actions.loadWorkflow()
                await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

                editLocally(logic)
                useWorkflowMock(
                    makeWorkflow({
                        actions: [...makeWorkflow().actions, branch(['trial']), emailStep('follow_up', 'Follow-up')],
                        edges: [
                            { from: 'trigger_node', to: 'branch', type: 'continue' },
                            { from: 'branch', to: 'follow_up', type: 'branch', index: 0 },
                            { from: 'branch', to: 'exit_node', type: 'continue' },
                            { from: 'follow_up', to: 'exit_node', type: 'continue' },
                        ],
                        updated_at: NEWER,
                    })
                )
                jest.useFakeTimers()

                await reconcileExternalEdit()

                const saved = (await flushAutoSave()) as HogFlow
                const savedBranch = saved.actions.find((action) => action.id === 'branch')!
                expect((savedBranch.config as Record<string, any>).conditions).toEqual(
                    expectedConditions.map((filters) => ({ filters }))
                )
                expect(saved.edges).toEqual(expectedEdges)
                expect(danglingEdges(saved)).toEqual([])
            }
        )
    })

    it('keeps an edit typed while the reload is in flight', async () => {
        useWorkflowMock(makeWorkflow({ updated_at: NEWER }))
        jest.useFakeTimers()

        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
            logic.actions.setWorkflowValue('name', 'Typed during the reload')
        }).toDispatchActions(['setSyncingExternalEdit', 'loadWorkflow', 'loadWorkflowSuccess'])

        expect(logic.values.workflow.name).toBe('Typed during the reload')
        const saved = await flushAutoSave()
        expect(saved.name).toBe('Typed during the reload')
    })

    it('lets the server copy win when the flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_KEEP_LOCAL_EDITS]: false })
        logic.actions.setWorkflowValue('name', 'My local edit')
        useWorkflowMock(makeWorkflow({ name: 'Renamed elsewhere', updated_at: NEWER }))

        await reconcileExternalEdit()

        expect(logic.values.workflow.name).toBe('Renamed elsewhere')
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('warns instead of clobbering when auto-save is off and there are unsaved local edits', async () => {
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
        [
            'the workflow has no name, so auto-save cannot flush',
            (l: ReturnType<typeof workflowLogic.build>) => l.actions.setWorkflowValue('name', ''),
        ],
        [
            'only a manual save persists a pending schedule change',
            (l: ReturnType<typeof workflowLogic.build>) => l.actions.setScheduleStartsAt('2026-07-01T00:00:00.000Z'),
        ],
    ])('warns instead of reloading when %s', async (_label, makeDirty) => {
        makeDirty(logic)
        expect(logic.values.hasUnsavedChanges).toBe(true)

        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setExternallyEdited'])

        expect(logic.values.externallyEdited).toBe(true)
        expect(getCalls).toBe(1)
    })

    it('reloads over dirty edits despite action validation errors (incomplete steps stage safely)', async () => {
        // The co-editing case: an active workflow with a half-built email step. Its validation
        // errors must not park the user's buffer as unflushable, or an agent edit arriving via SSE
        // dead-ends behind a banner instead of reconciling.
        const withInvalidEmail = makeWorkflow({
            status: 'active',
            actions: [
                ...makeWorkflow().actions,
                {
                    id: 'email_node',
                    type: 'function_email',
                    name: 'Email',
                    description: '',
                    created_at: 0,
                    updated_at: 0,
                    config: { template_id: 'template-email', inputs: { email: { value: {} } } },
                },
            ] as HogFlow['actions'],
        })
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    getCalls += 1
                    return [200, withInvalidEmail]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        logic.actions.loadWorkflow()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        expect(logic.values.workflowHasErrors).toBe(true)
        const baselineGets = getCalls

        logic.actions.setWorkflowValue('name', 'My local edit')
        expect(logic.values.hasUnsavedChanges).toBe(true)

        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setSyncingExternalEdit', 'loadWorkflow', 'loadWorkflowSuccess'])

        expect(logic.values.externallyEdited).toBe(false)
        expect(getCalls).toBe(baselineGets + 1)
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

    // The server emits resource_edited during our own PATCH/reload, and the SSE echo can land
    // before the HTTP response does. Reacting to it against the stale baseline flashed the
    // conflict banner at the user on every staged auto-save - but plain dropping would lose a
    // genuine concurrent edit arriving in the same window.
    it('defers events during our own flight, then reconciles genuine edits against the fresh baseline', async () => {
        logic.actions.setAutoSaveEnabled(false)
        logic.actions.setWorkflowValue('name', 'My local edit')
        expect(logic.values.hasUnsavedChanges).toBe(true)

        logic.actions.loadWorkflow()
        expect(logic.values.originalWorkflowLoading).toBe(true)
        resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))

        // No banner while our own flight is up.
        expect(logic.values.externallyEdited).toBe(false)

        // Once the flight settles, the parked event replays. The loaded baseline is still older
        // than the event, so the (now clean) editor silently syncs with a fresh load - the event
        // is reconciled, not dropped.
        await expectLogic(logic).toDispatchActions([
            'loadWorkflowSuccess',
            'replayDeferredResourceEdited',
            'setSyncingExternalEdit',
            'loadWorkflowSuccess',
        ])
        expect(logic.values.externallyEdited).toBe(false)
        expect(getCalls).toBe(3)
    })

    it('ignores the echo of our own staged draft save', async () => {
        // A staged save doesn't bump the live updated_at; the emit broadcasts the draft stamp
        // instead. That echo must not read as an external edit, or every auto-save on an active
        // workflow would flash the conflict banner (or trigger a reload loop).
        const DRAFT_AT = '2026-05-15T00:00:00.000Z'
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    getCalls += 1
                    return [200, makeWorkflow({ draft: { edges: [] }, draft_updated_at: DRAFT_AT })]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        logic.actions.loadWorkflow()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        const baselineGets = getCalls

        resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: DRAFT_AT }))
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(getCalls).toBe(baselineGets)
        expect(logic.values.externallyEdited).toBe(false)
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

    it('shows the banner when a manual save is rejected as stale (409 backstop)', async () => {
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

    it('shows the banner when an auto-save 409s with a pending schedule change, instead of reloading it away', async () => {
        // Only a manual save persists a schedule change, so the silent-reload path would wipe it.
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    getCalls += 1
                    return [200, makeWorkflow()]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': () => [409, { detail: 'stale_update' }],
            },
        })
        logic.actions.setScheduleStartsAt('2026-07-01T00:00:00.000Z')
        logic.actions.setWorkflowValue('name', 'Conflicting edit')
        const baselineGets = getCalls

        await expectLogic(logic, () => {
            logic.actions.markAutoSave(true)
            logic.actions.saveWorkflow(logic.values.workflow)
        }).toDispatchActions(['saveWorkflowFailure'])

        expect(logic.values.externallyEdited).toBe(true)
        expect(getCalls).toBe(baselineGets)
    })

    it('silently reloads when an auto-save is rejected as stale, instead of showing the banner', async () => {
        silenceKeaLoadersErrors() // the 409 save failure is the scenario under test
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    getCalls += 1
                    return [200, makeWorkflow({ updated_at: NEWER })]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    if (body.base_updated_at !== NEWER) {
                        return [409, { detail: 'stale_update' }]
                    }
                    savedBodies.push(body)
                    return [200, { ...makeWorkflow({ updated_at: NEWER }), ...body }]
                },
            },
        })
        logic.actions.setWorkflowValue('name', 'Conflicting edit')
        jest.useFakeTimers()

        await expectLogic(logic, () => {
            // The public shape of an auto-save: the autoSaveWorkflow listener marks the flight
            // before dispatching the save (skipping its debounce here).
            logic.actions.markAutoSave(true)
            logic.actions.saveWorkflow(logic.values.workflow)
        }).toDispatchActions(['setSyncingExternalEdit', 'loadWorkflow', 'saveWorkflowFailure', 'loadWorkflowSuccess'])

        expect(logic.values.externallyEdited).toBe(false)
        expect(logic.values.isSyncingExternalEdit).toBe(false)
        expect(getCalls).toBe(2)

        const saved = await flushAutoSave()
        expect(saved.name).toBe('Conflicting edit')
    })
})
