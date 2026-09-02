import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

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
            logic = workflowLogic({ id: WORKFLOW_ID })
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

        it('resets isAutoSave after auto-save completes', async () => {
            jest.useFakeTimers()

            logic.actions.setWorkflowValue('name', 'Edited')
            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])

            expect(logic.values.isAutoSave).toBe(false)
            expect(updateCalls).toBe(1)
        })

        it('keeps edits made while the save request is in flight and saves them next', async () => {
            jest.useFakeTimers()
            useMocks({
                patch: {
                    '/api/environments/:team_id/hog_flows/:id/': () => {
                        updateCalls += 1
                        return [200, { ...workflow, name: 'Edit 1' }]
                    },
                },
            })

            logic.actions.setWorkflowValue('name', 'Edit 1')
            await expectLogic(logic, () => {
                logic.actions.markAutoSave(true)
                logic.actions.saveWorkflow(logic.values.workflow)
                // Typed while the request is still in flight: the response won't carry it.
                logic.actions.setWorkflowValue('name', 'Edit 1 and more')
            }).toDispatchActions(['saveWorkflowSuccess'])
            expect(updateCalls).toBe(1)

            expect(logic.values.workflow.name).toBe('Edit 1 and more')
            expect(logic.values.workflowChanged).toBe(true)

            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toDispatchActions(['saveWorkflow', 'saveWorkflowSuccess'])
            expect(updateCalls).toBe(2)
        })

        it('does not re-save when nothing changed during the round-trip', async () => {
            jest.useFakeTimers()

            logic.actions.setWorkflowValue('name', 'Edited')
            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])

            await jest.advanceTimersByTimeAsync(3500)
            expect(updateCalls).toBe(1)
            expect(logic.values.workflowChanged).toBe(false)
        })
    })

    describe('skip cases', () => {
        it.each([
            ['new workflow', { id: 'new' as const }],
            ['template editing', { id: WORKFLOW_ID, editTemplateId: 'tpl-1' }],
        ])('does not auto-save for %s', async (_label, props) => {
            initKeaTests()
            logic = workflowLogic({ ...props })
            logic.mount()

            jest.useFakeTimers()
            logic.actions.autoSaveWorkflow()
            await jest.advanceTimersByTimeAsync(3500)

            expect(updateCalls).toBe(0)
        })

        it('does not auto-save when there are validation errors', async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
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
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            jest.useFakeTimers()
            logic.actions.autoSaveWorkflow()
            await jest.advanceTimersByTimeAsync(3500)

            expect(updateCalls).toBe(0)
        })

        it('clears isAutoSavePending when auto-save is skipped', async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            jest.useFakeTimers()

            // Dispatch auto-save without actual changes — guard will skip
            logic.actions.autoSaveWorkflow()
            expect(logic.values.isAutoSavePending).toBe(true)

            await jest.advanceTimersByTimeAsync(3500)
            expect(logic.values.isAutoSavePending).toBe(false)
            expect(updateCalls).toBe(0)
        })
    })

    describe('active workflows stage drafts', () => {
        // Active-status validation requires the trigger to have at least one event, or every save
        // (auto-save included) is refused.
        const activeWorkflow = makeWorkflow({
            status: 'active',
            actions: makeWorkflow().actions.map((action) =>
                action.id === 'trigger_node'
                    ? {
                          ...action,
                          config: {
                              type: 'event',
                              filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }] },
                          },
                      }
                    : action
            ) as HogFlow['actions'],
        })
        let patchBodies: Record<string, any>[]

        const renameExit = (actions: HogFlow['actions'], name: string): HogFlow['actions'] =>
            actions.map((action) => (action.id === 'exit_node' ? { ...action, name } : action))

        // Passed to useMocks inside each test: a helper that calls useMocks itself trips the
        // rules-of-hooks lint (the "use" prefix reads as a React hook).
        const activeMocks = (getResponse: HogFlow): Parameters<typeof useMocks>[0] => ({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': getResponse,
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    updateCalls += 1
                    const body = (await request.json()) as Record<string, any>
                    patchBodies.push(body)
                    // Server-faithful echo: a staged save keeps the live content and returns the
                    // new draft blob; a live save applies the payload.
                    return [
                        200,
                        body.stage_draft
                            ? {
                                  ...getResponse,
                                  name: body.name ?? getResponse.name,
                                  draft: { actions: body.actions, edges: body.edges },
                                  draft_updated_at: '2026-05-02T00:00:00.000Z',
                              }
                            : { ...getResponse, ...body },
                    ]
                },
            },
        })

        beforeEach(() => {
            patchBodies = []
        })

        it('auto-saves an active workflow as a staged draft, keeping the edits on the canvas', async () => {
            useMocks(activeMocks(activeWorkflow))
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            jest.useFakeTimers()
            logic.actions.setWorkflowValue('actions', renameExit(activeWorkflow.actions, 'Renamed exit'))
            // Fire the debounce under fake timers, then let the request itself run on real timers:
            // reading the mock request body (`request.json()`) parks on a macrotask fake timers never run.
            await jest.advanceTimersByTimeAsync(3100)
            jest.useRealTimers()
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])

            expect(updateCalls).toBe(1)
            expect(patchBodies[0].stage_draft).toBe(true)
            // The staged-save echo carries the old live content plus the draft; rebaselining the form
            // must not wipe the just-saved edits off the canvas.
            expect(logic.values.workflow.actions.find((a) => a.id === 'exit_node')?.name).toBe('Renamed exit')
            expect(logic.values.hasStagedDraft).toBe(true)
        })

        it('auto-saves despite action validation errors: incomplete steps stage safely into the draft', async () => {
            // The user's iterating case: an email step exists but has no content/sender yet. Pausing
            // auto-save here strands their edits unsaved while an agent keeps writing to the server.
            const withInvalidEmail = {
                ...activeWorkflow,
                actions: [
                    ...activeWorkflow.actions,
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
            }
            useMocks(activeMocks(withInvalidEmail))
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
            expect(logic.values.workflowHasErrors).toBe(true)

            jest.useFakeTimers()
            logic.actions.setWorkflowValue('actions', renameExit(withInvalidEmail.actions, 'Renamed exit'))
            await jest.advanceTimersByTimeAsync(3100)
            jest.useRealTimers()
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])

            expect(updateCalls).toBe(1)
            expect(patchBodies[0].stage_draft).toBe(true)
        })

        it('opens the staged draft in the editor when one exists', async () => {
            useMocks(
                activeMocks({
                    ...activeWorkflow,
                    draft: {
                        actions: renameExit(activeWorkflow.actions, 'Staged exit'),
                        edges: activeWorkflow.edges,
                    },
                    draft_updated_at: '2026-05-02T00:00:00.000Z',
                })
            )
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            expect(logic.values.workflow.actions.find((a) => a.id === 'exit_node')?.name).toBe('Staged exit')
            expect(logic.values.hasStagedDraft).toBe(true)
            // The merged draft is the clean baseline, not an unsaved change.
            expect(logic.values.workflowChanged).toBe(false)
        })

        it('a metadata-only save on an active workflow applies live without staging a phantom draft', async () => {
            useMocks(activeMocks(activeWorkflow))
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            jest.useFakeTimers()
            logic.actions.setWorkflowValue('name', 'Renamed active')
            await jest.advanceTimersByTimeAsync(3100)
            jest.useRealTimers()
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])

            // Renaming must not route unchanged content into the draft slot: the body carries
            // neither content fields nor the staging flag.
            expect(patchBodies[0].stage_draft).toBeUndefined()
            expect(patchBodies[0].actions).toBeUndefined()
            expect(patchBodies[0].name).toBe('Renamed active')
            expect(logic.values.hasStagedDraft).toBe(false)
        })

        it('a status transition sends lifecycle and metadata only, never stage_draft', async () => {
            useMocks(
                activeMocks({
                    ...activeWorkflow,
                    draft: {
                        actions: renameExit(activeWorkflow.actions, 'Staged exit'),
                        edges: activeWorkflow.edges,
                    },
                    draft_updated_at: '2026-05-02T00:00:00.000Z',
                })
            )
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            await expectLogic(logic, () => {
                logic.actions.saveWorkflowPartial({ status: 'draft' })
            }).toDispatchActions(['saveWorkflowSuccess'])

            // Disabling must not deploy the staged draft the form is showing.
            expect(patchBodies[0].stage_draft).toBeUndefined()
            expect(patchBodies[0].actions).toBeUndefined()
            expect(patchBodies[0].status).toBe('draft')
        })
    })

    describe('auto-save toggle', () => {
        beforeEach(async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
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
    })

    describe('a save that overlaps another save', () => {
        let serverUpdatedAt: string
        let rejected: number
        let releaseFirstPatch: (() => void) | null
        let firstPatchSeen: Promise<void>
        let scheduleWrites: number
        let events: string[]

        beforeEach(async () => {
            serverUpdatedAt = '2026-05-01T00:00:00.000Z'
            rejected = 0
            scheduleWrites = 0
            events = []
            releaseFirstPatch = null
            let markFirstPatchSeen = (): void => {}
            firstPatchSeen = new Promise<void>((resolve) => {
                markFirstPatchSeen = resolve
            })
            let patches = 0

            useMocks({
                get: {
                    '/api/environments/:team_id/hog_flows/:id/': () => [
                        200,
                        makeWorkflow({ updated_at: serverUpdatedAt }),
                    ],
                    '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
                },
                post: {
                    '/api/environments/:team_id/hog_flows/:id/schedules': () => {
                        scheduleWrites += 1
                        events.push('schedule')
                        return [200, { id: 'sched-1', rrule: 'FREQ=DAILY', starts_at: '2026-07-01T00:00:00.000Z' }]
                    },
                },
                patch: {
                    // Stands in for perform_update, which rejects a write whose base_updated_at is
                    // older than the stored stamp with a 409.
                    '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        patches += 1
                        // Hold the first save open so the second one overlaps it, the way a slow
                        // save on a large workflow does.
                        if (patches === 1) {
                            await new Promise<void>((resolve) => {
                                releaseFirstPatch = resolve
                                markFirstPatchSeen()
                            })
                        }
                        if (body.base_updated_at && body.base_updated_at < serverUpdatedAt) {
                            rejected += 1
                            return [409, { detail: 'stale_update', code: 'stale_update' }]
                        }
                        serverUpdatedAt = new Date(Date.parse(serverUpdatedAt) + 1000).toISOString()
                        events.push('patch')
                        return [200, makeWorkflow({ updated_at: serverUpdatedAt, name: body.name })]
                    },
                },
            })

            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        })

        it('does not raise the conflict banner at the only editor', async () => {
            logic.actions.setWorkflowValue('name', 'Renamed by me')
            await expectLogic(logic).toDispatchActions(['saveWorkflow'])
            await firstPatchSeen

            // The user clicks "Save draft" while the auto-save is still in flight.
            logic.actions.submitWorkflow()
            await new Promise((resolve) => setTimeout(resolve, 50))

            releaseFirstPatch?.()
            await new Promise((resolve) => setTimeout(resolve, 200))

            expect({ rejected, banner: logic.values.externallyEdited }).toEqual({ rejected: 0, banner: false })
        })

        it('runs the manual-only save work once when a manual save queues behind an auto-save', async () => {
            // Both saves now land, where the second used to 409. The auto-save must not pick up the
            // manual save's label and repeat its side effects, which include creating a schedule.
            logic.actions.setScheduleStartsAt('2026-07-01T00:00:00.000Z')

            logic.actions.setWorkflowValue('name', 'Renamed by me')
            await expectLogic(logic).toDispatchActions(['saveWorkflow'])
            await firstPatchSeen

            logic.actions.submitWorkflow()
            await new Promise((resolve) => setTimeout(resolve, 50))

            releaseFirstPatch?.()
            await new Promise((resolve) => setTimeout(resolve, 300))

            // The schedule belongs to the manual save, so it is written once and only after that
            // save lands. Attributing it to the auto-save puts it between the two patches.
            expect(events).toEqual(['patch', 'patch', 'schedule'])
            expect(scheduleWrites).toBe(1)
        })

        it("ignores the second queued save's own edit event", async () => {
            // The loader's loading flag is one boolean, so the first save clears it while the
            // second still runs. An echo of the second save arriving in that window used to read
            // as somebody else's edit, which is the false banner this whole change removes.
            resourceEditedLogic.mount()
            // Both saves are held, so the second is provably still open when the echo arrives.
            const release: (() => void)[] = []
            let held = 0
            let sawSecond = (): void => {}
            const secondPatchSeen = new Promise<void>((resolve) => {
                sawSecond = resolve
            })
            let loads = 0
            useMocks({
                get: {
                    '/api/environments/:team_id/hog_flows/:id/': () => {
                        loads += 1
                        return [200, makeWorkflow({ updated_at: serverUpdatedAt })]
                    },
                },
                patch: {
                    '/api/environments/:team_id/hog_flows/:id/': async () => {
                        held += 1
                        if (held === 2) {
                            sawSecond()
                        }
                        await new Promise<void>((resolve) => release.push(resolve))
                        return [200, makeWorkflow({ updated_at: '2026-05-01T00:00:0' + held + '.000Z' })]
                    },
                },
            })

            logic.actions.setWorkflowValue('name', 'Renamed by me')
            await expectLogic(logic).toDispatchActions(['saveWorkflow'])
            await new Promise((resolve) => setTimeout(resolve, 50))

            logic.actions.submitWorkflow()
            await new Promise((resolve) => setTimeout(resolve, 50))

            release[0]()
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])
            await secondPatchSeen

            // The first save has landed and the second is still open. Its own emit arrives now.
            resourceEditedLogic.actions.resourceEdited({
                notification_type: 'resource_edited',
                team_id: 1,
                resource_type: 'HogFlow',
                resource_id: WORKFLOW_ID,
                updated_at: '2027-01-01T00:00:00.000Z',
                actor_user_id: 1,
            })
            await new Promise((resolve) => setTimeout(resolve, 200))

            // Reacting here means treating this editor's own in-flight save as somebody else's:
            // a reload that resets the form under the person, or the banner.
            expect({ reloads: loads, banner: logic.values.externallyEdited }).toEqual({
                reloads: 0,
                banner: false,
            })

            release[1]()
            await new Promise((resolve) => setTimeout(resolve, 300))
        })

        it('keeps the form submitting until the queued manual save lands', async () => {
            logic.actions.setWorkflowValue('name', 'Renamed by me')
            await expectLogic(logic).toDispatchActions(['saveWorkflow'])
            await firstPatchSeen

            logic.actions.submitWorkflow()
            await new Promise((resolve) => setTimeout(resolve, 50))

            // The save button reads this. While it stays true the button cannot fire a second save.
            expect(logic.values.isWorkflowSubmitting).toBe(true)

            releaseFirstPatch?.()
            await new Promise((resolve) => setTimeout(resolve, 200))

            expect(logic.values.isWorkflowSubmitting).toBe(false)
        })
    })

    describe('draft actions on an active workflow', () => {
        const staged = makeWorkflow({
            status: 'active',
            draft: { name: 'Autosave test', actions: [], edges: [] },
            draft_updated_at: '2026-05-01T00:01:00.000Z',
        })

        beforeEach(async () => {
            useMocks({
                get: { '/api/environments/:team_id/hog_flows/:id/': staged },
                patch: { '/api/environments/:team_id/hog_flows/:id/': () => [200, staged] },
            })
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        })

        it('keeps the draft actions mounted and blocks publish while edits are unsaved', () => {
            logic.actions.setWorkflowValue('name', 'Still typing')

            expect(logic.values.hasUnsavedChanges).toBe(true)
            // Hiding these on a dirty form moved a different action under the pointer every time
            // auto-save landed.
            expect(logic.values.showDraftActions).toBe(true)
            // Publish promotes the staged draft, not what is on screen.
            expect(logic.values.publishDisabledReason).toBe('Save your changes first')
            // Discarding reloads the workflow, which would drop the edits still in the form.
            expect(logic.values.discardDisabledReason).toBe('Save or clear your changes first')
        })

        it('allows publish once auto-save clears the unsaved edits', async () => {
            jest.useFakeTimers()

            logic.actions.setWorkflowValue('name', 'Edited')
            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toDispatchActions(['saveWorkflowSuccess'])

            expect(logic.values.publishDisabledReason).toBeUndefined()
            expect(logic.values.discardDisabledReason).toBeUndefined()
        })

        it('still stages content when a queued save undoes the edit the previous save wrote', async () => {
            // Comparing against kea's copy would compare this edit with the state from two saves
            // ago. The undo then looks like no change at all, so its payload carries no content and
            // the draft keeps the step the user just deleted, which publishing would deploy.
            const patched: Record<string, any>[] = []
            let releaseFirst: () => void = () => {}
            let seen = 0
            const base = staged.actions
            const withStep = [
                ...base,
                {
                    id: 'delay_node',
                    type: 'delay',
                    name: 'Wait',
                    description: '',
                    created_at: 0,
                    updated_at: 0,
                    config: { delay_duration: '5m' },
                },
            ] as HogFlow['actions']
            // Start from a draft that holds the live steps, so reverting lands exactly back on it.
            const loaded = makeWorkflow({
                ...staged,
                draft: { ...(staged.draft as any), actions: base, edges: staged.edges },
            })

            useMocks({
                get: { '/api/environments/:team_id/hog_flows/:id/': loaded },
                patch: {
                    '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        patched.push(body)
                        if (++seen === 1) {
                            await new Promise<void>((resolve) => {
                                releaseFirst = resolve
                            })
                        }
                        // A staged save answers with the live row plus the new draft blob.
                        return [
                            200,
                            makeWorkflow({
                                ...loaded,
                                draft: { ...(loaded.draft as any), actions: body.actions ?? base },
                                draft_updated_at: new Date(Date.parse('2026-05-01T00:02:00.000Z') + seen).toISOString(),
                            }),
                        ]
                    },
                },
            })

            logic.actions.loadWorkflow()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            // Add a step, let that save start, then take it back out while it is still open.
            logic.actions.setWorkflowValues({ actions: withStep })
            logic.actions.markAutoSave(true)
            logic.actions.saveWorkflow(logic.values.workflow)
            await new Promise((resolve) => setTimeout(resolve, 50))

            logic.actions.setWorkflowValues({ actions: base })
            logic.actions.markAutoSave(true)
            logic.actions.saveWorkflow(logic.values.workflow)
            await new Promise((resolve) => setTimeout(resolve, 50))

            releaseFirst()
            await new Promise((resolve) => setTimeout(resolve, 400))

            // The undo must reach the draft, not be dropped as "nothing changed".
            expect(patched[1]?.actions?.map((a: any) => a.id)).toEqual(base.map((a) => a.id))
            expect(patched[1]?.stage_draft).toBe(true)
        })

        it('does not re-enable a workflow when a save is queued behind a disable', async () => {
            // The disable request is held open, so the save below queues behind it and carries the
            // form's stale status. Landing that would put a stopped workflow back into sending.
            const patched: Record<string, any>[] = []
            let releaseDisable: () => void = () => {}
            let seen = 0
            useMocks({
                patch: {
                    '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, any>
                        patched.push(body)
                        if (++seen === 1) {
                            await new Promise<void>((resolve) => {
                                releaseDisable = resolve
                            })
                        }
                        return [200, makeWorkflow({ ...staged, status: body.status ?? 'draft' })]
                    },
                },
            })

            logic.actions.saveWorkflowPartial({ status: 'draft' })
            await new Promise((resolve) => setTimeout(resolve, 50))

            logic.actions.setWorkflowValue('name', 'Edited while disabling')
            logic.actions.submitWorkflow()
            await new Promise((resolve) => setTimeout(resolve, 50))

            releaseDisable()
            await new Promise((resolve) => setTimeout(resolve, 300))

            expect(patched[0].status).toBe('draft')
            // The queued form save must not speak about status at all.
            expect(patched[1]).not.toHaveProperty('status')
        })
    })

    describe('navigation guard', () => {
        it('does not fire save on unmount (no silent flush)', async () => {
            initKeaTests()
            logic = workflowLogic({ id: WORKFLOW_ID })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            logic.actions.setWorkflowValue('name', 'Unsaved edit')
            expect(logic.values.hasUnsavedChanges).toBe(true)

            logic.unmount()
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(updateCalls).toBe(0)
        })

        it('does not warn on navigation for new workflows', async () => {
            // The beforeUnload guard skips when id is 'new', even if
            // the form has unsaved changes (e.g. freshly created draft).
            initKeaTests()
            logic = workflowLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

            logic.actions.setWorkflowValue('name', 'My new workflow')
            expect(logic.values.hasUnsavedChanges).toBe(true)
            // Guard condition: props.id === 'new' → skip
            expect(logic.props.id).toBe('new')
        })
    })
})
