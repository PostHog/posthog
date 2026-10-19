import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-send-once-verified-1'
const UNVERIFIED_SENDER = { id: 7, domain: 'example.com' }

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

    const mountWith = async (workflow: HogFlow, { flagOn = true } = {}): Promise<void> => {
        storedWorkflow = workflow
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: flagOn })
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
    }

    beforeEach(() => {
        patchBodies = []
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [200, storedWorkflow],
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
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
    })

    it('asks before enabling a workflow with an unverified sender, naming the domain', async () => {
        await mountWith(makeWorkflow({ unverified_email_senders: [UNVERIFIED_SENDER] }))

        await expectLogic(logic, () => {
            logic.actions.saveWorkflowPartial({ status: 'active' })
        })
            .toDispatchActions(['openEnablePrompt'])
            .toNotHaveDispatchedActions(['saveWorkflow'])
            .toMatchValues({ enablePromptDomains: ['example.com'] })
        expect(patchBodies).toEqual([])
    })

    it('saves the usual active status once the person confirms, and shows the waiting status', async () => {
        await mountWith(makeWorkflow({ unverified_email_senders: [UNVERIFIED_SENDER] }))
        logic.actions.saveWorkflowPartial({ status: 'active' })

        await expectLogic(logic, () => {
            logic.actions.confirmEnablePrompt()
        })
            .toDispatchActions(['saveWorkflowSuccess'])
            .toMatchValues({ enablePromptDomains: null })
        expect(patchBodies.map((body) => body.status)).toEqual(['active'])
        expect(logic.values.originalWorkflow?.status).toEqual('waiting_for_domain')
    })

    it('leaves the workflow off when the person cancels', async () => {
        await mountWith(makeWorkflow({ unverified_email_senders: [UNVERIFIED_SENDER] }))
        logic.actions.saveWorkflowPartial({ status: 'active' })

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
            logic.actions.saveWorkflowPartial({ status: 'active' })
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
})
