import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { draftMessage } from '../MessageAudience/messageDrafts'
import { HogFlowAction } from './hogflows/types'
import { NEW_WORKFLOW, workflowLogic } from './workflowLogic'

const SANDBOX: Partial<IntegrationType> = {
    id: 7,
    kind: 'email',
    display_name: 'Example via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', verified: true, email: 'sandbox@example.com' },
}
const OWN_VERIFIED: Partial<IntegrationType> = {
    id: 5,
    kind: 'email',
    config: { provider: 'ses', verified: true, email: 'own@example.com' },
}

type EmailValue = { from?: Record<string, unknown>; replyTo?: string }

const emailAction = (type: 'function_email' | 'function', value: EmailValue = {}): HogFlowAction =>
    ({
        id: 'email',
        type,
        name: 'Send email',
        description: '',
        config: {
            template_id: 'template-email',
            inputs: {
                email: {
                    value: {
                        from: {},
                        to: { email: 'member@example.com' },
                        subject: 'Welcome',
                        html: '<p>Your account is ready.</p>',
                        ...value,
                    },
                    templating: 'liquid',
                },
            },
        },
    }) as HogFlowAction

const emailValueOf = (logic: ReturnType<typeof workflowLogic>, id = 'email'): Record<string, any> | undefined =>
    (logic.values.workflow.actions.find((step) => step.id === id)?.config as any)?.inputs?.email?.value

describe('workflow first-run sender', () => {
    let ensureCalls: number
    let ensureFails: number
    let integrations: Partial<IntegrationType>[]
    let action: HogFlowAction

    const setSandboxFlag = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: enabled })
    }

    const loadTemplate = async (): Promise<ReturnType<typeof workflowLogic>> => {
        const logic = workflowLogic({ id: 'new', templateId: 'first-run-example' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        return logic
    }

    beforeEach(() => {
        integrations = []
        ensureCalls = 0
        ensureFails = 0
        action = emailAction('function_email')
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [200, { results: integrations }],
                '/api/projects/:team_id/hog_flow_templates/:id/': () => [
                    200,
                    { ...NEW_WORKFLOW, actions: [NEW_WORKFLOW.actions[0], action, NEW_WORKFLOW.actions[1]] },
                ],
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                    ensureCalls++
                    if (ensureFails > 0) {
                        ensureFails--
                        return [500, { detail: 'Unavailable' }]
                    }
                    integrations = [...integrations, SANDBOX]
                    return [200, SANDBOX]
                },
            },
        })
        initKeaTests()
        setSandboxFlag(true)
    })

    it.each<{
        name: string
        step: HogFlowAction
        senders: Partial<IntegrationType>[]
        flag: boolean
        expectedFrom: Record<string, unknown>
        expectedEnsureCalls: number
    }>([
        {
            name: 'an email step in a project without senders gets the sandbox sender',
            step: emailAction('function_email'),
            senders: [],
            flag: true,
            expectedFrom: { integrationId: SANDBOX.id },
            expectedEnsureCalls: 1,
        },
        {
            name: 'an existing sandbox sender is reused',
            step: emailAction('function_email'),
            senders: [SANDBOX],
            flag: true,
            expectedFrom: { integrationId: SANDBOX.id },
            expectedEnsureCalls: 0,
        },
        {
            name: 'a verified own sender wins over the sandbox sender',
            step: emailAction('function_email'),
            senders: [OWN_VERIFIED, SANDBOX],
            flag: true,
            expectedFrom: { integrationId: OWN_VERIFIED.id },
            expectedEnsureCalls: 0,
        },
        {
            name: 'several verified own senders leave the choice to the person',
            step: emailAction('function_email'),
            senders: [OWN_VERIFIED, { ...OWN_VERIFIED, id: 6 }, SANDBOX],
            flag: true,
            expectedFrom: {},
            expectedEnsureCalls: 0,
        },
        {
            name: 'a generic email function never gets the sandbox sender',
            step: emailAction('function'),
            senders: [],
            flag: true,
            expectedFrom: {},
            expectedEnsureCalls: 0,
        },
        {
            name: 'a configured Reply-To keeps the sandbox sender off',
            step: emailAction('function_email', { replyTo: 'reply@example.com' }),
            senders: [],
            flag: true,
            expectedFrom: {},
            expectedEnsureCalls: 0,
        },
        {
            name: 'a custom From address keeps the sandbox sender off',
            step: emailAction('function_email', { from: { email: 'hello@example.com' } }),
            senders: [],
            flag: true,
            expectedFrom: { email: 'hello@example.com' },
            expectedEnsureCalls: 0,
        },
        {
            name: 'a configured sender stays',
            step: emailAction('function_email', { from: { integrationId: 12 } }),
            senders: [OWN_VERIFIED],
            flag: true,
            expectedFrom: { integrationId: 12 },
            expectedEnsureCalls: 0,
        },
        {
            name: 'flag off leaves a step without own senders empty',
            step: emailAction('function_email'),
            senders: [SANDBOX],
            flag: false,
            expectedFrom: {},
            expectedEnsureCalls: 0,
        },
        {
            name: 'flag off fills a custom From address with the own default sender, as before',
            step: emailAction('function_email', { from: { email: 'hello@example.com' } }),
            senders: [OWN_VERIFIED],
            flag: false,
            expectedFrom: { email: 'hello@example.com', integrationId: OWN_VERIFIED.id },
            expectedEnsureCalls: 0,
        },
        {
            name: 'flag on fills a custom From address with the own default sender too',
            step: emailAction('function_email', { from: { email: 'hello@example.com' } }),
            senders: [OWN_VERIFIED],
            flag: true,
            expectedFrom: { email: 'hello@example.com', integrationId: OWN_VERIFIED.id },
            expectedEnsureCalls: 0,
        },
    ])('$name', async ({ step, senders, flag, expectedFrom, expectedEnsureCalls }) => {
        action = step
        integrations = senders
        setSandboxFlag(flag)

        const logic = await loadTemplate()

        expect(emailValueOf(logic)).toMatchObject({ subject: 'Welcome', html: '<p>Your account is ready.</p>' })
        expect(emailValueOf(logic)?.from).toEqual(expectedFrom)
        expect(ensureCalls).toBe(expectedEnsureCalls)
        logic.unmount()
    })

    it.each([
        ['a template', { templateId: 'first-run-example' }],
        [
            'a trigger prefill',
            {
                triggerPrefill: JSON.stringify({
                    type: 'event',
                    filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events' }] },
                }),
                emailPrefill: JSON.stringify(draftMessage({ kind: 'issue_hit' })),
            },
        ],
    ])('reports the sandbox preselection once for a workflow from %s', async (_source, prefillProps) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const logic = workflowLogic({ id: 'new', ...prefillProps })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])

        const email = logic.values.workflow.actions.find((step) => step.type === 'function_email')
        expect((email?.config as any)?.inputs?.email?.value?.from).toEqual({ integrationId: SANDBOX.id })
        expect(capture.mock.calls.filter(([event]) => event === 'email sender preselected')).toEqual([
            ['email sender preselected', { surface: 'workflow', reason: 'sandbox_sender' }],
        ])
        capture.mockRestore()
        logic.unmount()
    })

    it('finds a verified own sender on a later page of the sender list', async () => {
        const unverifiedOwn = (id: number): Partial<IntegrationType> => ({
            id,
            kind: 'email',
            config: { provider: 'ses', verified: false, email: `own${id}@example.com` },
        })
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': ({ request }) =>
                    new URL(request.url).searchParams.get('offset') === '100'
                        ? [200, { results: [OWN_VERIFIED], next: null }]
                        : [
                              200,
                              {
                                  results: Array.from({ length: 100 }, (_, index) => unverifiedOwn(100 + index)),
                                  next: 'next-page',
                              },
                          ],
            },
        })

        const logic = await loadTemplate()

        expect(emailValueOf(logic)?.from).toEqual({ integrationId: OWN_VERIFIED.id })
        expect(ensureCalls).toBe(0)
        logic.unmount()
    })

    it.each([
        ['nothing is cached', false],
        ['an earlier list is cached', true],
    ])('opens the editor without a sender when the sender list cannot load and %s', async (_case, cached) => {
        integrations = [OWN_VERIFIED]
        const unmountIntegrations = cached ? integrationsLogic.mount() : () => undefined
        if (cached) {
            await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])
        }
        useMocks({ get: { '/api/projects/:team_id/integrations/': () => [500, { detail: 'Unavailable' }] } })

        const logic = await loadTemplate()
        unmountIntegrations()

        expect(emailValueOf(logic)?.from).toEqual({})
        expect(ensureCalls).toBe(0)
        logic.unmount()
    })

    it('tries to set up the sandbox sender again on the next load after a failure', async () => {
        ensureFails = 1

        const logic = await loadTemplate()
        expect(emailValueOf(logic)?.from).toEqual({})

        await expectLogic(logic, () => logic.actions.loadWorkflow()).toDispatchActions(['loadWorkflowSuccess'])
        expect(emailValueOf(logic)?.from).toEqual({ integrationId: SANDBOX.id })
        expect(ensureCalls).toBe(2)
        logic.unmount()
    })
})
