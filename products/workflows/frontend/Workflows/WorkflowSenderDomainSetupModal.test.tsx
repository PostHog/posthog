import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { FakeEmailDomainBackend } from '../Channels/EmailDomain/__mocks__/fakeEmailDomainBackend'
import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowSenderDomainSetupModal } from './WorkflowSenderDomainSetupModal'
import { WorkflowStatusBar } from './WorkflowStatusBar'

const WORKFLOW_ID = 'wf-domain-setup-1'
const DOMAIN = 'mail.acme.com'
const SENDER_ID = 42

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

const flush = async (): Promise<void> => {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(0)
    })
}

describe('the email domain setup opened from a workflow', () => {
    let backend: FakeEmailDomainBackend
    let storedWorkflow: HogFlow
    let savedStatuses: string[]

    const openFromStatusBar = async (workflow: HogFlow): Promise<void> => {
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
        fireEvent.click(element('workflow-sender-domain-status'))
        await flush()
        expect(screen.getByText('For the workflow Welcome new sign-ups')).toBeInTheDocument()
    }

    beforeEach(() => {
        jest.useFakeTimers()
        savedStatuses = []
        backend = new FakeEmailDomainBackend()
        backend.hostDnsAt('acme.com', 'cloudflare')
        backend.addSender({ email: `hello@${DOMAIN}` })
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
                    savedStatuses.push(String(body.status))
                    return [200, { ...storedWorkflow, status: 'waiting_for_domain' }]
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
        jest.useRealTimers()
    })

    it('enables a draft to send once verified while DNS is checked, and closes over the workflow', async () => {
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

        expect(savedStatuses).toEqual(['active'])
        expect(screen.queryByText('For the workflow Welcome new sign-ups')).not.toBeInTheDocument()
    })

    it.each<{ name: string; workflow: () => HogFlow; text: string }>([
        {
            name: 'says why a workflow without a sender cannot be enabled',
            workflow: () => workflowWith({}, {}),
            text: "Choose a sender in the workflow's email step first.",
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
        backend.publishRecords(DOMAIN)
        await openFromStatusBar(workflow())
        expect(screen.getByText(text)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="email-domain-workflow-enable"]')).toBeNull()

        fireEvent.click(element('email-domain-workflow-back'))
        await flush()

        expect(savedStatuses).toEqual([])
        expect(screen.queryByText('For the workflow Welcome new sign-ups')).not.toBeInTheDocument()
    })

    it('offers to enable the workflow once the domain is verified', async () => {
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
})
