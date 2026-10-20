import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import type { SenderDomainNotice } from './senderDomainNotice'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-send-once-verified-1'
const UNVERIFIED_SENDER = { id: 7, domain: 'example.com' }

interface ProjectSender {
    id: number
    domain: string
    verified: boolean
}
const PENDING_PROJECT_SENDER: ProjectSender = { ...UNVERIFIED_SENDER, verified: false }
const VERIFIED_PROJECT_SENDER: ProjectSender = { id: 8, domain: 'mail.example.org', verified: true }

const emailStep = (from: Record<string, unknown>): HogFlow['actions'][number] =>
    ({
        id: 'email_node',
        type: 'function_email',
        name: 'Welcome email',
        description: '',
        created_at: 0,
        updated_at: 0,
        config: { template_id: 'template-email', inputs: { email: { value: { from, to: {}, subject: 'Hi' } } } },
    }) as HogFlow['actions'][number]

const withEmailStep = (workflow: HogFlow, from: Record<string, unknown>): HogFlow => ({
    ...workflow,
    actions: [workflow.actions[0], emailStep(from), workflow.actions[1]],
})

const makeWorkflow = (overrides: Partial<HogFlow> = {}): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'Welcome',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                type: 'event',
                filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }] },
            },
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
    updated_at: '2026-05-01T00:00:00.000Z',
    unverified_email_senders: [],
    ...overrides,
})

describe('workflowLogic send once verified', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let patchBodies: Record<string, any>[]
    let storedWorkflow: HogFlow
    let projectSenders: ProjectSender[]
    let retrieveCount: number

    const mountWith = async (
        workflow: HogFlow,
        { flagOn = true, senders = [PENDING_PROJECT_SENDER] }: { flagOn?: boolean; senders?: ProjectSender[] } = {}
    ): Promise<void> => {
        storedWorkflow = workflow
        projectSenders = senders
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: flagOn })
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        await expectLogic(integrationsLogic).toFinishAllListeners()
    }

    beforeEach(() => {
        patchBodies = []
        retrieveCount = 0
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => {
                    retrieveCount += 1
                    return [200, storedWorkflow]
                },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
                '/api/projects/:team_id/integrations/': () => [
                    200,
                    {
                        results: projectSenders.map(({ id, domain, verified }) => ({
                            id,
                            kind: 'email',
                            config: { domain, verified },
                        })),
                        count: projectSenders.length,
                        next: null,
                    },
                ],
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    patchBodies.push((await request.json()) as Record<string, any>)
                    return [200, { ...storedWorkflow, status: 'waiting_for_domain', enable_requested_at: '2026-05-02' }]
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    it('asks before enabling a workflow with an unverified sender, naming the domain', async () => {
        await mountWith(makeWorkflow({ unverified_email_senders: [UNVERIFIED_SENDER] }))

        await expectLogic(logic, () => {
            logic.actions.enableWorkflow()
        })
            .toDispatchActions(['openEnablePrompt'])
            .toNotHaveDispatchedActions(['saveWorkflow'])
            .toMatchValues({ enablePromptDomains: ['example.com'] })
        expect(patchBodies).toEqual([])
    })

    it('saves the usual active status once the person confirms, and shows the waiting status', async () => {
        await mountWith(makeWorkflow({ unverified_email_senders: [UNVERIFIED_SENDER] }))
        logic.actions.enableWorkflow()

        await expectLogic(logic, () => {
            logic.actions.confirmEnablePrompt()
        })
            .toDispatchActions(['saveWorkflowSuccess'])
            .toMatchValues({ enablePromptDomains: null })
        expect(patchBodies.map((body) => body.status)).toEqual(['active'])
        expect(logic.values.originalWorkflow?.status).toEqual('waiting_for_domain')
    })

    it.each([
        ['succeeds', 200, 'saveWorkflowSuccess'],
        ['fails', 500, 'saveWorkflowFailure'],
    ])('keeps the prompt open and loading until the enable save %s', async (_name, responseCode, settledAction) => {
        await mountWith(makeWorkflow({ unverified_email_senders: [UNVERIFIED_SENDER] }))
        let releaseSave!: () => void
        const saveReleased = new Promise<void>((resolve) => {
            releaseSave = resolve
        })
        useMocks({
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    patchBodies.push((await request.json()) as Record<string, any>)
                    await saveReleased
                    return [responseCode, { ...storedWorkflow, status: 'waiting_for_domain' }]
                },
            },
        })
        logic.actions.enableWorkflow()

        await expectLogic(logic, () => {
            logic.actions.confirmEnablePrompt()
        })
            .toDispatchActions(['saveWorkflow'])
            .toMatchValues({ enablePromptDomains: ['example.com'], workflowLoading: true })

        releaseSave()
        await expectLogic(logic)
            .toDispatchActions([settledAction])
            .toMatchValues({ enablePromptDomains: null, workflowLoading: false })
        expect(patchBodies.map((body) => body.status)).toEqual(['active'])
    })

    it('leaves the workflow off when the person cancels', async () => {
        await mountWith(makeWorkflow({ unverified_email_senders: [UNVERIFIED_SENDER] }))
        logic.actions.enableWorkflow()

        await expectLogic(logic, () => {
            logic.actions.cancelEnablePrompt()
        })
            .toNotHaveDispatchedActions(['saveWorkflow'])
            .toMatchValues({ enablePromptDomains: null })
        expect(patchBodies).toEqual([])
        expect(logic.values.originalWorkflow?.status).toEqual('draft')
    })

    it.each([
        ['the flag is off', [UNVERIFIED_SENDER], false],
        ['every sender is verified', [], true],
    ])('enables without asking when %s', async (_name, senders, flagOn) => {
        await mountWith(makeWorkflow({ unverified_email_senders: senders }), { flagOn })

        await expectLogic(logic, () => {
            logic.actions.enableWorkflow()
        })
            .toDispatchActions(['saveWorkflowSuccess'])
            .toMatchValues({ enablePromptDomains: null })
        expect(patchBodies.map((body) => body.status)).toEqual(['active'])
    })

    it('shows the started sending notice once after a waited go-live, until it is dismissed', async () => {
        const wentLive = makeWorkflow({
            status: 'active',
            enable_requested_at: '2026-05-02T10:00:00Z',
            went_live_at: '2026-05-03T08:30:00Z',
        })
        await mountWith(wentLive)
        expect(logic.values.showStartedSendingNotice).toBe(true)

        logic.actions.dismissStartedSendingNotice()
        expect(logic.values.showStartedSendingNotice).toBe(false)

        logic.unmount()
        await mountWith(wentLive)
        expect(logic.values.showStartedSendingNotice).toBe(false)

        logic.unmount()
        await mountWith({ ...wentLive, went_live_at: '2026-05-09T08:30:00Z' })
        expect(logic.values.showStartedSendingNotice).toBe(true)
    })

    it.each([
        [
            'a direct enable',
            { status: 'active', enable_requested_at: '2026-05-02T10:00:00Z', went_live_at: '2026-05-02T10:00:00Z' },
        ],
        ['a workflow still waiting', { status: 'waiting_for_domain', enable_requested_at: '2026-05-02T10:00:00Z' }],
        [
            'a workflow turned off after it went live',
            { status: 'draft', enable_requested_at: '2026-05-02T10:00:00Z', went_live_at: '2026-05-03T08:30:00Z' },
        ],
    ] as [string, Partial<HogFlow>][])('shows no started sending notice for %s', async (_name, overrides) => {
        await mountWith(makeWorkflow(overrides))

        expect(logic.values.showStartedSendingNotice).toBe(false)
    })

    it.each<{
        name: string
        status: HogFlow['status']
        from: Record<string, unknown>
        unverified: { id: number; domain: string }[]
        senders: ProjectSender[]
        flagOn?: boolean
        notice: SenderDomainNotice | null
    }>([
        {
            name: 'a step has no sender and the project has a verified sender',
            status: 'draft',
            from: {},
            unverified: [],
            senders: [PENDING_PROJECT_SENDER, VERIFIED_PROJECT_SENDER],
            notice: null,
        },
        {
            name: 'a step has no sender and the project has no sender',
            status: 'draft',
            from: {},
            unverified: [],
            senders: [],
            notice: { stage: 'no_domain', url: '/workflows/channels' },
        },
        {
            name: 'a step has no sender and the project only has a pending domain',
            status: 'draft',
            from: {},
            unverified: [],
            senders: [PENDING_PROJECT_SENDER],
            notice: { stage: 'unverified', domains: ['example.com'], url: '/workflows/channels' },
        },
        {
            name: 'the sender of a step was deleted and the project has no other sender',
            status: 'draft',
            from: { integrationId: 99 },
            unverified: [],
            senders: [],
            notice: { stage: 'no_domain', url: '/workflows/channels' },
        },
        {
            name: 'a draft sends from an unverified domain',
            status: 'draft',
            from: { integrationId: 7 },
            unverified: [UNVERIFIED_SENDER],
            senders: [PENDING_PROJECT_SENDER, VERIFIED_PROJECT_SENDER],
            notice: { stage: 'unverified', domains: ['example.com'], url: '/workflows/channels' },
        },
        {
            name: 'an enabled workflow waits for its domain',
            status: 'waiting_for_domain',
            from: { integrationId: 7 },
            unverified: [UNVERIFIED_SENDER],
            senders: [PENDING_PROJECT_SENDER],
            notice: { stage: 'waiting', domains: ['example.com'], url: '/workflows/channels' },
        },
        {
            name: 'every sender is verified',
            status: 'active',
            from: { integrationId: 8 },
            unverified: [],
            senders: [VERIFIED_PROJECT_SENDER],
            notice: null,
        },
        {
            name: 'the flag is off',
            status: 'draft',
            from: {},
            unverified: [],
            senders: [],
            flagOn: false,
            notice: null,
        },
    ])('shows the sender domain notice when $name', async ({ status, from, unverified, senders, flagOn, notice }) => {
        await mountWith(withEmailStep(makeWorkflow({ status, unverified_email_senders: unverified }), from), {
            flagOn,
            senders,
        })

        expect(logic.values.senderDomainNotice).toEqual(notice)
    })

    it('shows no sender domain notice for a workflow without an email step', async () => {
        await mountWith(makeWorkflow())

        expect(logic.values.senderDomainNotice).toBeNull()
    })

    describe('while the workflow waits for its domain', () => {
        const waiting = makeWorkflow({
            status: 'waiting_for_domain',
            enable_requested_at: '2026-05-02T10:00:00Z',
            unverified_email_senders: [UNVERIFIED_SENDER],
        })
        const wentLive: HogFlow = {
            ...waiting,
            status: 'active',
            went_live_at: '2026-05-03T08:30:00Z',
            updated_at: '2026-05-03T08:30:00Z',
            unverified_email_senders: [],
        }

        const mountWaiting = async (): Promise<void> => {
            jest.useFakeTimers({ advanceTimers: true })
            await mountWith(waiting)
            retrieveCount = 0
        }

        it('shows the workflow going live without a reload, keeps unsaved edits, and stops checking', async () => {
            await mountWaiting()
            logic.actions.setAutoSaveEnabled(false)
            logic.actions.setWorkflowValue('name', 'Renamed while waiting')
            storedWorkflow = wentLive

            await jest.advanceTimersByTimeAsync(10_000)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.originalWorkflow?.status).toEqual('active')
            expect(logic.values.showStartedSendingNotice).toBe(true)
            expect(logic.values.senderDomainNotice).toBeNull()
            expect(logic.values.workflow.name).toEqual('Renamed while waiting')
            expect(logic.values.hasUnsavedChanges).toBe(true)

            await jest.advanceTimersByTimeAsync(60_000)
            expect(retrieveCount).toEqual(1)
        })

        it('stages later edits as a draft of the live copy, without a conflict', async () => {
            useMocks({
                patch: {
                    '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                        patchBodies.push((await request.json()) as Record<string, any>)
                        return [200, storedWorkflow]
                    },
                },
            })
            await mountWaiting()
            logic.actions.setAutoSaveEnabled(false)
            storedWorkflow = wentLive
            await jest.advanceTimersByTimeAsync(10_000)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setWorkflowValue('exit_condition', 'exit_on_conversion')
            await expectLogic(logic, () => {
                logic.actions.submitWorkflow()
            }).toDispatchActions(['saveWorkflowSuccess'])

            expect(patchBodies).toEqual([
                expect.objectContaining({
                    exit_condition: 'exit_on_conversion',
                    stage_draft: true,
                    base_updated_at: wentLive.updated_at,
                }),
            ])
        })

        it('drops a status answer that lands after the editor closed', async () => {
            await mountWaiting()
            let releaseCheck!: () => void
            const checkReleased = new Promise<void>((resolve) => {
                releaseCheck = resolve
            })
            useMocks({
                get: {
                    '/api/environments/:team_id/hog_flows/:id/': async () => {
                        retrieveCount += 1
                        await checkReleased
                        return [200, wentLive]
                    },
                },
            })
            await jest.advanceTimersByTimeAsync(10_000)
            expect(retrieveCount).toEqual(1)

            logic.unmount()
            releaseCheck()
            await jest.advanceTimersByTimeAsync(0)
            await new Promise((resolve) => setImmediate(resolve))
        })

        it('checks only while the tab is visible, and checks at once when it shows again', async () => {
            let hidden = true
            const hiddenSpy = jest.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden)
            try {
                await mountWaiting()
                document.dispatchEvent(new Event('visibilitychange'))

                await jest.advanceTimersByTimeAsync(60_000)
                expect(retrieveCount).toEqual(0)

                storedWorkflow = wentLive
                hidden = false
                document.dispatchEvent(new Event('visibilitychange'))
                await jest.advanceTimersByTimeAsync(0)
                await expectLogic(logic).toFinishAllListeners()

                expect(retrieveCount).toEqual(1)
                expect(logic.values.originalWorkflow?.status).toEqual('active')
            } finally {
                hiddenSpy.mockRestore()
            }
        })
    })
})
