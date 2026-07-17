import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { attachedContextLogic } from '../../api/logics'
import { composerSeedLogic } from '../../logics/composerSeedLogic'
import { toolStreamEventsLogic } from '../../logics/toolStreamEventsLogic'
import { OriginProduct, Task, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

const buildTask = (overrides: Partial<Task> = {}): Task => ({
    id: 'task-1',
    task_number: 1,
    slug: 'task-1',
    title: 'Some task',
    description: 'do the thing',
    origin_product: OriginProduct.POSTHOG_AI,
    repository: null,
    github_integration: null,
    signal_report: null,
    json_schema: null,
    internal: false,
    latest_run: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    created_by: null,
    ...overrides,
})

describe('taskTrackerSceneLogic', () => {
    let logic: ReturnType<typeof taskTrackerSceneLogic.build>
    let createBody: Record<string, any> | null
    let runBody: Record<string, any> | null
    let toolEvents: ReturnType<typeof toolStreamEventsLogic.build>

    beforeEach(() => {
        createBody = null
        runBody = null
        useMocks({
            get: {
                '/api/projects/:team/tasks/': { results: [], count: 0 },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
                '/api/environments/:team/integrations/': { results: [] },
            },
            post: {
                '/api/projects/:team/tasks/': async ({ request }) => {
                    createBody = (await request.json()) as Record<string, any>
                    return [200, { id: 'new-task', ...createBody }]
                },
                '/api/projects/:team/tasks/:id/run/': async ({ request }) => {
                    runBody = (await request.json()) as Record<string, any>
                    return [200, { id: 'new-task', latest_run: 'run-1' }]
                },
            },
        })
        initKeaTests()
        toolEvents = toolStreamEventsLogic()
        toolEvents.mount()
        toolEvents.actions.registerToolListener('editor', {
            tools: ['create_insight'],
            applyBackTargetId: 'insight-1:activation-1',
            onEvent: jest.fn(),
        })
        logic = taskTrackerSceneLogic()
    })

    afterEach(() => {
        logic?.unmount()
        toolEvents?.unmount()
    })

    // PostHog AI can run without a repo: a description-only submit must still create and run the task with a
    // null repository, not bail. Guards against re-adding a "Repository is required" gate on the send path.
    it('creates and runs a task with no repository selected', async () => {
        logic.mount()
        logic.actions.setNewTaskData({ description: 'do the thing' })
        logic.actions.submitNewTask()

        await expectLogic(logic).toFinishAllListeners()

        expect(createBody).toMatchObject({
            description: 'do the thing',
            origin_product: OriginProduct.POSTHOG_AI,
            repository: null,
            github_integration: null,
        })
        // Interactive so the sandbox event stream survives across turns (follow-ups stream), and the
        // typed message is seeded as turn 1 (interactive runs boot with the agent pulling it from run
        // state). Dropping either regresses follow-up streaming / loses the first prompt.
        expect(runBody).toMatchObject({
            mode: 'interactive',
            pending_user_message: 'do the thing',
        })
        const streamKey = logic.values.activeCreation?.streamKey
        expect(streamKey).not.toBeUndefined()
        expect(toolEvents.values.applyBackTargetClaims[streamKey!]).toEqual([
            { targetId: 'insight-1:activation-1', tools: ['create_insight'] },
        ])
        expect(router.values.location.pathname).toContain('/tasks/new-task')
    })

    // The seeded first message wraps the on-screen context, and the wrapped non-text refs must be marked
    // sent under the created task's id — otherwise the run's first follow-up (sent via
    // `runInteractionLogic`, which prunes against the task-scoped store) re-wraps the same refs.
    it('marks seeded context sent for the created task so the first follow-up will not re-wrap it', async () => {
        logic.mount()
        attachedContextLogic().actions.registerContext('scene', [
            { type: 'insight', key: 'sig', label: 'Signups' },
            { type: 'text', value: 'always resend me' },
        ])

        logic.actions.setNewTaskData({ description: 'why the drop?' })
        logic.actions.submitNewTask()
        await expectLogic(logic).toFinishAllListeners()

        // The message sent to the agent is wrapped; the task description stays raw.
        expect(runBody?.pending_user_message).toContain('<posthog_untrusted_context>')
        expect(runBody?.pending_user_message).toContain('- insight sig ("Signups")')
        expect(createBody?.description).toBe('why the drop?')
        // Only the entity ref is marked sent (text items always resend), under the created task's id.
        expect(attachedContextLogic().values.sentContextKeysByTask).toEqual({ 'new-task': ['insight:sig'] })
    })

    // The tasks backend has no server-side consent check (unlike the conversations coordinator), so a
    // send must be blocked client-side before it ever reaches `api.tasks.create` — otherwise a sandbox
    // run starts with zero consent enforcement. Uses a distinct `panelId` key so the logic is built
    // (and connects to `aiConsentLogic`) after the selector is stubbed.
    it('blocks submitNewTask without creating a task when AI data processing consent is not accepted', async () => {
        const consent = aiConsentLogic()
        consent.mount()
        jest.spyOn(consent.selectors, 'dataProcessingAccepted').mockReturnValue(false)

        const blockedLogic = taskTrackerSceneLogic({ panelId: 'consent-test' })
        blockedLogic.mount()
        blockedLogic.actions.setNewTaskData({ description: 'do the thing' })
        blockedLogic.actions.submitNewTask()

        await expectLogic(blockedLogic).toFinishAllListeners()

        expect(createBody).toBeNull()
        expect(blockedLogic.values.consentBlocked).toBe(true)
        expect(blockedLogic.values.isSubmittingTask).toBe(false)

        blockedLogic.unmount()
        consent.unmount()
        jest.restoreAllMocks()
    })

    // The repo picker only renders once `repositoryConfig.integrationId` is set (auto-selected from the
    // connected GitHub org). Submitting resets the form, wiping that id; without re-deriving it the picker
    // stays blank for every subsequent new task. Guards that the auto-select is restored after a submit.
    it('restores the repository integration after a submit so the picker reappears', async () => {
        useMocks({
            get: {
                '/api/environments/:team/integrations/': {
                    results: [{ id: 7, kind: 'github', display_name: 'acme/widgets', config: {} }],
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        // Auto-selected on mount once the integration list loads — the picker is showing.
        expect(logic.values.newTaskData.repositoryConfig.integrationId).toBe(7)

        logic.actions.setNewTaskData({ description: 'ship it' })
        logic.actions.submitNewTask()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.newTaskData.repositoryConfig.integrationId).toBe(7)
    })

    // An embedded instance (e.g. Max's side panel runner) keeps the run in place instead of navigating the
    // host to `/tasks/:id`, and must never have its `activeCreation` cleared by unrelated main-app
    // navigation. Guards against either guard (`props.panelId` in `submitNewTask` / `urlToAction`) being
    // dropped, which would yank the host to the tasks scene or silently drop the panel's in-flight run.
    it('does not navigate on create and ignores url cleanup for an embedded instance', async () => {
        const panelLogic = taskTrackerSceneLogic({ panelId: 'test-panel' })
        panelLogic.mount()
        const initialPath = router.values.location.pathname

        panelLogic.actions.setNewTaskData({ description: 'do the thing' })
        panelLogic.actions.submitNewTask()
        await expectLogic(panelLogic).toFinishAllListeners()

        expect(router.values.location.pathname).toBe(initialPath)
        expect(panelLogic.values.activeCreation).toMatchObject({ taskId: 'new-task' })

        router.actions.push('/tasks/some-other-task')
        expect(panelLogic.values.activeCreation).toMatchObject({ taskId: 'new-task' })

        panelLogic.unmount()
    })

    // Opening a task from the panel's history must render its run in place (a task with a run) or fall
    // back to the full detail page (a task that never ran) — never the other way round.
    it.each([
        {
            description: 'a task with a latest run',
            task: buildTask({
                id: 'task-with-run',
                latest_run: {
                    id: 'run-1',
                    task: 'task-with-run',
                    stage: null,
                    branch: null,
                    status: TaskRunStatus.COMPLETED,
                    environment: TaskRunEnvironment.CLOUD,
                    log_url: null,
                    error_message: null,
                    output: null,
                    state: {},
                    artifacts: [],
                    created_at: '2026-01-01T00:00:00Z',
                    updated_at: '2026-01-01T00:00:00Z',
                    completed_at: '2026-01-01T00:00:00Z',
                },
            }),
            expectedActiveCreation: { streamKey: 'run-1', taskId: 'task-with-run', runId: 'run-1' },
            expectedPath: undefined,
        },
        {
            description: 'a task that never ran',
            task: buildTask({ id: 'task-without-run', latest_run: null }),
            expectedActiveCreation: null,
            expectedPath: '/tasks/task-without-run',
        },
    ])('openExistingTask opens $description', ({ task, expectedActiveCreation, expectedPath }) => {
        logic.mount()
        const initialPath = router.values.location.pathname
        // Set beforehand to prove opening a task resets it, even for the never-ran/navigate case.
        logic.actions.toggleHistory()
        expect(logic.values.historyExpanded).toBe(true)

        logic.actions.openExistingTask(task)

        expect(logic.values.activeCreation).toEqual(expectedActiveCreation)
        expect(logic.values.historyExpanded).toBe(false)
        expect(router.values.location.pathname).toContain(expectedPath ?? initialPath)
    })

    // A CTA opens the panel and stamps its prompt onto composerSeedLogic BEFORE the composer mounts, so the
    // seed must be picked up on mount — this is the live breakage the seam fixes (the prompt was dropped).
    // autoSubmit=false must only prefill, never send. Guards the afterMount pickup, the consume-once clear,
    // and that a non-auto seed doesn't submit.
    it('picks up a seed set before mount and prefills without submitting when autoSubmit is false', async () => {
        const seedLogic = composerSeedLogic()
        seedLogic.mount()
        seedLogic.actions.setSeed({ prompt: 'analyze churn', autoSubmit: false })

        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.newTaskData.description).toBe('analyze churn')
        expect(seedLogic.values.seed).toBeNull()
        // No submit: submitting opens an optimistic activeCreation, prefill-only leaves it null.
        expect(logic.values.activeCreation).toBeNull()

        seedLogic.unmount()
    })

    // A seed arriving while the composer is already mounted (the panel was open when another CTA fired) must
    // apply immediately via the setSeed listener, and autoSubmit=true must send it. Re-applying afterwards must
    // not re-submit — a reopened panel must never resend a stale prompt. Guards the listener path, the
    // auto-submit wiring, and consume-once.
    it('applies a seed that arrives while mounted, auto-submits it, and does not resubmit once consumed', async () => {
        let createCount = 0
        useMocks({
            post: {
                '/api/projects/:team/tasks/': async ({ request }) => {
                    createCount++
                    createBody = (await request.json()) as Record<string, any>
                    return [200, { id: 'new-task', ...createBody }]
                },
                '/api/projects/:team/tasks/:id/run/': () => [200, { id: 'new-task' }],
            },
        })

        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        composerSeedLogic().actions.setSeed({ prompt: 'summarize experiment', autoSubmit: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(createBody).toMatchObject({ description: 'summarize experiment', repository: null })
        expect(logic.values.activeCreation).toMatchObject({ taskId: 'new-task' })
        expect(composerSeedLogic().values.seed).toBeNull()
        expect(createCount).toBe(1)

        // Consumed seed is inert: re-triggering must not create a second task.
        logic.actions.applyComposerSeed()
        await expectLogic(logic).toFinishAllListeners()
        expect(createCount).toBe(1)
    })

    // A seed arriving while a submit is in flight must not start a second concurrent create/run (the two
    // requests would fight over the composer and activeCreation) and must not be lost: it stays pending and
    // applies once the submission resolves — auto-submitting then, or surviving the post-submit form reset
    // as a prefill. Guards the isSubmittingTask hold in applyComposerSeed and the reset-before-success order.
    it.each([
        { autoSubmit: true, expectedCreates: 2 },
        { autoSubmit: false, expectedCreates: 1 },
    ])(
        'holds a seed arriving mid-submit and applies it after the submission resolves (autoSubmit=$autoSubmit)',
        async ({ autoSubmit, expectedCreates }) => {
            let createCount = 0
            useMocks({
                post: {
                    '/api/projects/:team/tasks/': async ({ request }) => {
                        createCount++
                        createBody = (await request.json()) as Record<string, any>
                        return [200, { id: `task-${createCount}`, ...createBody }]
                    },
                    '/api/projects/:team/tasks/:id/run/': () => [200, { id: 'run-1' }],
                },
            })
            logic.mount()

            composerSeedLogic().actions.setSeed({ prompt: 'first', autoSubmit: true })
            // The first submit is now in flight; a second CTA fires before it resolves.
            composerSeedLogic().actions.setSeed({ prompt: 'second', autoSubmit })
            // Held, not applied: the seed is still pending and no second submission started.
            expect(composerSeedLogic().values.seed).toMatchObject({ prompt: 'second' })

            await expectLogic(logic).toFinishAllListeners()

            expect(createCount).toBe(expectedCreates)
            expect(composerSeedLogic().values.seed).toBeNull()
            if (autoSubmit) {
                expect(createBody).toMatchObject({ description: 'second' })
            } else {
                expect(logic.values.newTaskData.description).toBe('second')
            }
        }
    )
})
