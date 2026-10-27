import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { FakeEmailDomainBackend } from '../Channels/EmailDomain/__mocks__/fakeEmailDomainBackend'
import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowSenderDomainSetupModal } from './WorkflowSenderDomainSetupModal'
import { WorkflowStatusBar } from './WorkflowStatusBar'

const WORKFLOW_ID = 'wf-domain-setup-1'
const DOMAIN = 'mail.acme.com'
const SENDER_ID = 42
const POLL_MS = 10_000

const workflowWith = (overrides: Partial<HogFlow>, from: Record<string, unknown>): HogFlow =>
    ({
        id: WORKFLOW_ID,
        name: 'Welcome new sign-ups',
        version: 1,
        status: 'draft',
        team_id: 1,
        conversion: { filters: [] },
        exit_condition: 'exit_only_at_end',
        trigger: { type: 'event', filters: {} },
        edges: [
            { from: 'trigger_node', to: 'email_node', type: 'continue' },
            { from: 'email_node', to: 'exit_node', type: 'continue' },
        ],
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
                id: 'email_node',
                type: 'function_email',
                name: 'Welcome email',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: {
                    template_id: 'template-email',
                    inputs: {
                        email: {
                            value: {
                                from,
                                to: { email: '{{ person.properties.email }}' },
                                subject: 'Hi',
                                html: '<p>Hi</p>',
                                text: 'Hi',
                            },
                        },
                    },
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
        created_at: '2026-09-01T00:00:00.000Z',
        updated_at: '2026-09-01T00:00:00.000Z',
        unverified_email_senders: [],
        ...overrides,
    }) as HogFlow

const element = (attr: string): HTMLElement => {
    const found = document.querySelector<HTMLElement>(`[data-attr="${attr}"]`)
    if (!found) {
        throw new Error(`No element with data-attr ${attr} on the page`)
    }
    return found
}

const flush = async (ms = 0): Promise<void> => {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

const emailSenderOf = (workflow: Partial<HogFlow>, stepId: string): unknown =>
    (workflow.actions?.find(({ id }) => id === stepId)?.config as any)?.inputs?.email?.value?.from

describe('the email domain setup opened from a workflow', () => {
    let backend: FakeEmailDomainBackend
    let storedWorkflow: HogFlow
    let savedBodies: Partial<HogFlow>[]

    const savedStatuses = (): string[] => savedBodies.map((body) => String(body.status))

    const openFromStatusBar = async (
        workflow: HogFlow,
        link: 'workflow-sender-domain-status' | 'workflow-sender-domain-set-up' = 'workflow-sender-domain-status'
    ): Promise<void> => {
        storedWorkflow = workflow
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <WorkflowStatusBar
                        id={WORKFLOW_ID}
                        editorLayout="advanced"
                        showEditorLayoutToggle={false}
                        onEditorLayoutChange={() => {}}
                    />
                    <WorkflowSenderDomainSetupModal />
                </BindLogic>
            </Provider>
        )
        await flush()
        fireEvent.click(element(link))
        await flush()
        expect(screen.getByText('For the workflow Welcome new sign-ups')).toBeInTheDocument()
    }

    beforeEach(() => {
        jest.useFakeTimers()
        savedBodies = []
        backend = new FakeEmailDomainBackend()
        backend.hostDnsAt('acme.com', 'cloudflare')
        const fakeMocks = backend.mocks()
        const listSenders = fakeMocks.get?.['/api/environments/:team_id/integrations/']
        if (!listSenders) {
            throw new Error('The fake email backend no longer lists senders')
        }
        useMocks({
            ...fakeMocks,
            get: {
                ...fakeMocks.get,
                '/api/projects/:team_id/integrations/': listSenders,
                '/api/environments/:team_id/hog_flows/:id/': () => [200, storedWorkflow],
                '/api/projects/:team_id/hog_function_templates/': {
                    results: [
                        {
                            id: 'template-email',
                            name: 'Email',
                            type: 'destination',
                            inputs_schema: [{ type: 'native_email', key: 'email', label: 'Email', required: true }],
                        },
                    ],
                    count: 1,
                },
            },
            patch: {
                ...fakeMocks.patch,
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    const body = (await request.json()) as Partial<HogFlow>
                    savedBodies.push(body)
                    const enabling = body.status === 'active'
                    storedWorkflow = {
                        ...storedWorkflow,
                        ...body,
                        status: enabling ? 'waiting_for_domain' : storedWorkflow.status,
                        updated_at: `2026-09-0${savedBodies.length + 1}T00:00:00.000Z`,
                    }
                    return [200, storedWorkflow]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: true,
        })
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('enables a draft to send once verified while DNS is checked, and closes over the workflow', async () => {
        backend.addSender({ email: `hello@${DOMAIN}` })
        backend.publishRecords(DOMAIN)
        await openFromStatusBar(
            workflowWith(
                { unverified_email_senders: [{ id: SENDER_ID, domain: DOMAIN }] },
                { integrationId: SENDER_ID }
            )
        )
        expect(screen.getByText(`It starts sending once ${DOMAIN} is verified.`)).toBeInTheDocument()
        expect(document.querySelector('[data-attr$="workflow-choices"]')).toBeNull()

        expect(element('email-domain-workflow-enable')).toHaveTextContent('Enable and send once verified')
        fireEvent.click(element('email-domain-workflow-enable'))
        await flush()

        expect(savedStatuses()).toEqual(['active'])
        expect(screen.queryByText('For the workflow Welcome new sign-ups')).not.toBeInTheDocument()
    })

    it.each<{ name: string; workflow: () => HogFlow; text: string }>([
        {
            name: 'says why a workflow without a sender cannot be enabled',
            workflow: () => workflowWith({}, {}),
            text: "Choose a sender in the workflow's email step first.",
        },
        {
            name: 'says why a viewer cannot enable the workflow',
            workflow: () =>
                workflowWith(
                    {
                        user_access_level: AccessControlLevel.Viewer,
                        unverified_email_senders: [{ id: SENDER_ID, domain: DOMAIN }],
                    },
                    { integrationId: SENDER_ID }
                ),
            text: 'You need editor access to enable this workflow.',
        },
        {
            name: 'skips the enable action for a workflow already waiting',
            workflow: () =>
                workflowWith(
                    { status: 'waiting_for_domain', unverified_email_senders: [{ id: SENDER_ID, domain: DOMAIN }] },
                    { integrationId: SENDER_ID }
                ),
            text: `It's on and starts sending once ${DOMAIN} is verified.`,
        },
    ])('$name, and Back to workflow only closes', async ({ workflow, text }) => {
        const capture = jest.spyOn(posthog, 'capture')
        backend.addSender({ email: `hello@${DOMAIN}` })
        backend.publishRecords(DOMAIN)
        await openFromStatusBar(workflow())
        expect(screen.getByText(text)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="email-domain-workflow-enable"]')).toBeNull()

        fireEvent.click(element('email-domain-workflow-back'))
        await flush()

        expect(savedStatuses()).toEqual([])
        expect(screen.queryByText('For the workflow Welcome new sign-ups')).not.toBeInTheDocument()
        expect(capture.mock.calls.filter(([event]) => event === 'email domain setup closed')).toEqual([
            ['email domain setup closed', { furthest_step: 'verifying', surface: 'workflow_editor', completed: false }],
        ])
    })

    it('offers to enable the workflow once the domain is verified', async () => {
        backend.addSender({ email: `hello@${DOMAIN}` })
        backend.verifyDomain(DOMAIN)
        await openFromStatusBar(
            workflowWith(
                { unverified_email_senders: [{ id: SENDER_ID, domain: DOMAIN }] },
                { integrationId: SENDER_ID }
            )
        )
        expect(screen.getByText(`${DOMAIN} is verified. Turn the workflow on to start sending.`)).toBeInTheDocument()
        expect(element('email-domain-workflow-enable')).toHaveTextContent('Enable workflow')
        expect(document.querySelector('[data-attr="email-domain-create-blank-workflow"]')).toBeNull()
    })

    it('fills the empty sender with the one created in the setup, so the fresh workflow enables in one step', async () => {
        await openFromStatusBar(workflowWith({}, {}), 'workflow-sender-domain-set-up')

        fireEvent.change(document.getElementById('email-domain-another-domain') as HTMLInputElement, {
            target: { value: 'acme.com' },
        })
        fireEvent.click(element('email-domain-use-custom-domain'))
        fireEvent.click(element('email-domain-continue'))
        await flush()

        expect(savedBodies.map((body) => emailSenderOf(body, 'email_node'))).toEqual([{ integrationId: SENDER_ID }])

        backend.publishRecords(DOMAIN)
        await flush(POLL_MS)
        const fillNotice = `Your workflow now sends from hello@${DOMAIN}.`
        expect(screen.getByText((_, node) => node?.tagName === 'P' && node.textContent === fillNotice)).toBeVisible()
        expect(element('email-domain-workflow-enable')).toHaveTextContent('Enable and send once verified')

        fireEvent.click(element('email-domain-workflow-enable'))
        await flush()

        expect(savedBodies.map((body) => body.status)).toEqual([undefined, 'active'])
        expect(emailSenderOf(storedWorkflow, 'email_node')).toEqual({ integrationId: SENDER_ID })
    })
})
