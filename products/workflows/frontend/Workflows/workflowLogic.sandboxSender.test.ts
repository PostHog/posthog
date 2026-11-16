import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { HogFlow, HogFlowAction } from './hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from './workflowLogic'

const EMAIL_ID = 'action_function_email_welcome'
const TEMPLATE_ID = 'template-welcome'

function templateWithEmail(
    value: Record<string, unknown> = {},
    config: Record<string, unknown> = {},
    emailId = EMAIL_ID
): HogFlow {
    return {
        ...NEW_WORKFLOW,
        id: TEMPLATE_ID,
        name: 'Welcome email',
        actions: [
            ...NEW_WORKFLOW.actions,
            {
                id: emailId,
                type: 'function_email',
                name: 'Email',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: {
                    template_id: 'template-email',
                    ...config,
                    inputs: {
                        email: {
                            templating: 'liquid',
                            value: {
                                to: { email: '{{ person.properties.email }}', name: '' },
                                from: {},
                                subject: 'Welcome',
                                text: 'Hello',
                                html: '<p>Hello</p>',
                                ...value,
                            },
                        },
                    },
                },
            } as HogFlowAction,
        ],
        edges: [
            { from: TRIGGER_NODE_ID, to: emailId, type: 'continue' },
            { from: emailId, to: EXIT_NODE_ID, type: 'continue' },
        ],
    }
}

const verifiedSender = { id: 7, kind: 'email', config: { verified: true, email: 'hi@example.com' } }

function integrationPages(integrations: unknown[]) {
    return ({ request }: { request: Request }): [number, Record<string, unknown>] => {
        const url = new URL(request.url)
        const kind = url.searchParams.get('kind')
        const limit = Number(url.searchParams.get('limit') ?? 100)
        const offset = Number(url.searchParams.get('offset') ?? 0)
        const matching = (integrations as { kind: string }[]).filter(
            (integration) => !kind || integration.kind === kind
        )
        const next = offset + limit < matching.length ? `${url.pathname}?offset=${offset + limit}&limit=${limit}` : null
        return [200, { results: matching.slice(offset, offset + limit), next }]
    }
}

const sandboxStatus = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
    integration_id: 11,
    from_address: 'sandbox@example.com',
    display_name: 'Acme via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
    ...overrides,
})

describe('workflowLogic first-run email sender', () => {
    let sandboxSenders: Record<string, number> = {}
    let events: { event: string; properties: unknown }[] = []

    function useSenderMocks(
        integrations: unknown[],
        status: Record<string, unknown>,
        provisionStatus = 200,
        template = templateWithEmail()
    ): void {
        sandboxSenders = {}
        events = []
        jest.mocked(posthog.capture).mockImplementation((event, properties) => {
            events.push({ event, properties })
            return undefined
        })
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/:id/': template,
                '/api/environments/:team_id/integrations/': integrationPages(integrations),
                '/api/projects/:team_id/integrations/': integrationPages(integrations),
                '/api/projects/:team_id/workflow_email_sandbox/status/': (req: any) => [
                    200,
                    { ...status, integration_id: sandboxSenders[req.params.team_id] ?? status.integration_id },
                ],
            },
            post: {
                '/api/projects/:team_id/workflow_email_sandbox/provision/': (req: any) => {
                    if (provisionStatus !== 200) {
                        return [provisionStatus, { detail: "This organization can't use the sandbox sender." }]
                    }
                    sandboxSenders[req.params.team_id] = 11
                    return [200, { integration_id: 11 }]
                },
            },
        })
    }

    async function openTemplate(team?: Partial<TeamType>): Promise<HogFlowAction | undefined> {
        initKeaTests()
        if (team) {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ...team })
        }
        const logic = workflowLogic({ id: 'new', templateId: TEMPLATE_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        const email = logic.values.workflow.actions.find((action) => action.name === 'Email')
        logic.unmount()
        return email
    }

    it.each([
        ['on the first page of integrations', [verifiedSender]],
        [
            'after a full page of unverified senders',
            [
                ...Array.from({ length: 100 }, (_, index) => ({
                    id: 100 + index,
                    kind: 'email',
                    config: { verified: false, email: `pending${index}@example.com` },
                })),
                verifiedSender,
            ],
        ],
    ])('prefers a verified own sender %s over the sandbox sender', async (_, integrations) => {
        useSenderMocks(integrations, sandboxStatus())

        const email = await openTemplate()

        expect(email?.type).toEqual('function_email')
        expect((email?.config as any).inputs.email.value.from).toEqual({ integrationId: 7 })
    })

    it.each([
        ['the sender is already set up', sandboxStatus(), []],
        [
            'the sender is set up on demand',
            sandboxStatus({ integration_id: null }),
            [{ event: 'workflows sandbox sender provisioned', properties: { surface: 'first_run' } }],
        ],
    ])('uses the sandbox sender when the project has no own sender and %s', async (_, status, expectedEvents) => {
        useSenderMocks([], status)

        const email = await openTemplate()

        expect(email?.type).toEqual('email_sandbox')
        expect((email?.config as any).inputs.email.value).toEqual({
            to: { email: '{{ person.properties.email }}' },
            subject: 'Welcome',
            text: 'Hello',
            html: '<p>Hello</p>',
        })
        expect(events.filter(({ event }) => event.startsWith('workflows sandbox'))).toEqual(expectedEvents)
    })

    it('sets up the sandbox sender in the selected environment rather than its project', async () => {
        const environmentId = MOCK_DEFAULT_TEAM.id + 1
        useSenderMocks([], sandboxStatus({ integration_id: null }))

        const email = await openTemplate({ id: environmentId })

        expect(email?.type).toEqual('email_sandbox')
        expect(sandboxSenders).toEqual({ [String(environmentId)]: 11 })
    })

    it.each([
        ['follows the team default', { utm_source: 'posthog' }, 'email_sandbox'],
        ['sets its own UTM tags', { utm_source: 'newsletter' }, 'function_email'],
    ])(
        'with team UTM tags on by default, a template email that %s gets the right sender',
        async (_, utmParams, expectedType) => {
            useSenderMocks(
                [],
                sandboxStatus(),
                200,
                templateWithEmail({}, { utm_tags_enabled: true, utm_params: utmParams })
            )

            const email = await openTemplate({
                workflows_config: { email_utm_tags_enabled: true, email_utm_params: { utm_source: 'posthog' } },
            } as Partial<TeamType>)

            expect(email?.type).toEqual(expectedType)
        }
    )

    it.each([
        ['adoption is off', [], sandboxStatus({ adoption_enabled: false }), 200, {}],
        ['the organization is blocked', [], sandboxStatus({ organization_blocked: true }), 200, {}],
        ['setting up the sender fails', [], sandboxStatus({ integration_id: null }), 403, {}],
        [
            'several own senders exist and none is the default',
            [verifiedSender, { ...verifiedSender, id: 8 }],
            sandboxStatus(),
            200,
            {},
        ],
        [
            'the email has a Reply-To the sandbox sender would drop',
            [],
            sandboxStatus({ integration_id: null }),
            200,
            { replyTo: 'help@example.com' },
        ],
        [
            'the step id is one the sandbox sender rejects',
            [],
            sandboxStatus({ integration_id: null }),
            200,
            {},
            'welcome.email',
        ],
    ])(
        'keeps an own email step without a sender when %s',
        async (_, integrations, status, provisionStatus, emailValue, emailId = EMAIL_ID) => {
            useSenderMocks(integrations, status, provisionStatus, templateWithEmail(emailValue, {}, emailId))

            const email = await openTemplate()

            expect(email?.type).toEqual('function_email')
            expect((email?.config as any).inputs.email.value).toMatchObject({ from: {}, ...emailValue })
            expect(sandboxSenders).toEqual({})
        }
    )
})
