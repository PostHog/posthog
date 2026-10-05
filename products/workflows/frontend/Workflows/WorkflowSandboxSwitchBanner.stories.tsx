import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import type { HogFlow } from './hogflows/types'
import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from './workflowLogic'
import { WorkflowSandboxSwitchBanner } from './WorkflowSandboxSwitchBanner'

const LOGIC_PROPS: WorkflowLogicProps = { id: 'storybook-sandbox-switch-banner' }

const SANDBOX_SENDER = {
    id: 7,
    kind: 'email',
    display_name: 'Acme via PostHog <sandbox@example.com>',
    config: { provider: 'sandbox', name: 'Acme via PostHog', email: 'sandbox@example.com', verified: true },
    created_at: '2026-08-18T00:00:00Z',
}

const OWN_SENDER = {
    id: 8,
    kind: 'email',
    display_name: 'Acme <hello@acme.example.com>',
    config: {
        provider: 'ses',
        name: 'Acme',
        email: 'hello@acme.example.com',
        domain: 'acme.example.com',
        verified: true,
    },
    created_at: '2026-08-18T00:00:00Z',
}

const SECOND_OWN_SENDER = {
    id: 9,
    kind: 'email',
    display_name: 'Acme support <support@acme.example.com>',
    config: {
        provider: 'ses',
        name: 'Acme support',
        email: 'support@acme.example.com',
        domain: 'acme.example.com',
        verified: true,
    },
    created_at: '2026-08-18T00:00:00Z',
}

const SANDBOX_WORKFLOW: HogFlow = {
    ...NEW_WORKFLOW,
    id: LOGIC_PROPS.id!,
    name: 'Welcome email',
    actions: [
        {
            id: 'trigger',
            type: 'trigger',
            name: 'New account created',
            description: '',
            config: { type: 'event', filters: {} },
        },
        {
            id: 'email',
            type: 'function_email',
            name: 'Send welcome email',
            description: '',
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: '{{ person.properties.email }}', name: '' },
                            from: { integrationId: SANDBOX_SENDER.id },
                            subject: 'Welcome aboard',
                            text: 'Your account is ready.',
                            html: '<p>Your account is ready.</p>',
                        },
                        templating: 'liquid',
                    },
                },
            },
        },
        { id: 'exit', type: 'exit', name: 'Exit', description: '', config: { reason: 'Completed' } },
    ],
    edges: [
        { from: 'trigger', to: 'email', type: 'continue' },
        { from: 'email', to: 'exit', type: 'continue' },
    ],
}

type StoryArgs = {
    ownSenders: (typeof OWN_SENDER)[]
    narrow?: boolean
}

const meta: Meta<StoryArgs> = {
    title: 'Products/Workflows/Sandbox switch banner',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER],
        testOptions: { waitForSelector: '[data-attr="workflow-sandbox-switch-sender"]' },
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ ownSenders, narrow }) => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/hog_flows/:id/': SANDBOX_WORKFLOW,
            '/api/projects/:team_id/integrations/': { results: [SANDBOX_SENDER, ...ownSenders] },
            '/api/projects/:team_id/hog_function_templates': { count: 0, results: [] },
            '/api/environments/:team_id/messaging_categories': { count: 0, results: [] },
        },
    })
    return (
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <div className={narrow ? 'w-[520px]' : 'max-w-4xl'}>
                <WorkflowSandboxSwitchBanner {...LOGIC_PROPS} />
            </div>
        </BindLogic>
    )
}

export const OneOwnSender = Template.bind({})
OneOwnSender.args = { ownSenders: [OWN_SENDER] }

export const OneOwnSenderNarrow = Template.bind({})
OneOwnSenderNarrow.args = { ownSenders: [OWN_SENDER], narrow: true }

export const SeveralOwnSenders = Template.bind({})
SeveralOwnSenders.args = { ownSenders: [OWN_SENDER, SECOND_OWN_SENDER] }

export const SeveralOwnSendersNarrow = Template.bind({})
SeveralOwnSendersNarrow.args = { ownSenders: [OWN_SENDER, SECOND_OWN_SENDER], narrow: true }
