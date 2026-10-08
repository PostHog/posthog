import type { Meta, StoryFn } from '@storybook/react'
import { ReactFlowProvider } from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import _hogFunctionTemplatesDestinations from '~/mocks/fixtures/_hogFunctionTemplatesDestinations.json'
import { HogFunctionTemplateType } from '~/types'

import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic, HogFlowEditorMode } from '../hogFlowEditorLogic'
import type { HogFlow, HogFlowAction } from '../types'
import { HogFlowEditorPanel } from './HogFlowEditorPanel'

const LOGIC_PROPS: WorkflowLogicProps = { id: 'storybook-configuration-panel' }

// The email template is hidden, so it is not in the shared destinations fixture. Mirrors
// nodejs/src/cdp/templates/_destinations/email/email.template.ts.
const EMAIL_TEMPLATE: HogFunctionTemplateType = {
    id: 'template-email',
    type: 'destination',
    name: 'Email',
    description: 'The email message to send. Configure the recipient, sender, subject, and content.',
    status: 'hidden',
    free: false,
    code: '',
    code_language: 'hog',
    icon_url: '/static/posthog-icon.svg',
    inputs_schema: [
        {
            type: 'native_email',
            key: 'email',
            label: 'Email message',
            integration: 'email',
            required: true,
            secret: false,
            description: 'The email message to send. Configure the recipient, sender, subject, and content.',
        },
    ],
}

const EMAIL_PREVIEW_HTML =
    '<html><body style="margin:0;font-family:sans-serif"><div style="background:#1d1f27;color:#fff;padding:24px">PostHog</div><div style="padding:24px"><h1 style="margin:0 0 8px">Welcome aboard</h1><p>Your account is ready to go.</p></div></body></html>'

const PANEL_WORKFLOW: HogFlow = {
    ...NEW_WORKFLOW,
    id: LOGIC_PROPS.id!,
    name: 'Configuration panel examples',
    variables: [
        { type: 'string', key: 'account_owner', label: 'Account owner', default: '' },
        { type: 'number', key: 'trial_days', label: 'Trial days', default: 14 },
        ...Array.from({ length: 22 }, (_, index) => ({
            type: 'string' as const,
            key: `workflow_value_${index + 1}`,
            label: `Workflow value ${index + 1}`,
            default: '',
        })),
    ],
    actions: [
        {
            id: 'trigger',
            type: 'trigger',
            name: 'New account created',
            description: 'Start when a new account is created.',
            config: {
                type: 'event',
                filters: { events: [{ id: 'account_created', name: 'Account created', type: 'events' }] },
            },
        },
        {
            id: 'delay',
            type: 'delay',
            name: 'Wait for activation',
            description: 'Give the account time to activate.',
            config: { delay_duration: '1d' },
        },
        {
            id: 'webhook',
            type: 'function',
            name: 'Send activation webhook',
            description: 'Send the activation event to an example endpoint.',
            config: {
                template_id: 'template-webhook',
                inputs: {
                    url: { value: 'https://example.com/hooks/activation' },
                    method: { value: 'POST' },
                    body: { value: { account_id: '{person.id}', event: '{event.event}' }, templating: 'hog' },
                },
            },
        },
        {
            id: 'email',
            type: 'function_email',
            name: 'Send welcome email',
            description: 'Welcome the account to the product.',
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: '{{ person.properties.email }}', name: '' },
                            from: { email: 'hello@example.com', name: 'Example' },
                            subject: 'Welcome aboard',
                            preheader: '',
                            text: 'Your account is ready to go.',
                            html: EMAIL_PREVIEW_HTML,
                        },
                        templating: 'liquid',
                    },
                },
            },
        },
        {
            id: 'conditional',
            type: 'conditional_branch',
            name: 'Route by account stage',
            description: 'Choose a path based on the account stage.',
            config: {
                conditions: [
                    {
                        name: 'Paid account',
                        filters: {
                            properties: [{ key: 'account_stage', value: ['paid'], operator: 'exact', type: 'person' }],
                        },
                    },
                    { name: 'Trial account', filters: {} },
                ],
            },
        },
        {
            id: 'cohort',
            type: 'random_cohort_branch',
            name: 'Choose onboarding path',
            description: 'Split accounts between two onboarding paths.',
            config: {
                cohorts: [
                    { name: 'Guided onboarding', percentage: 60 },
                    { name: 'Self-serve onboarding', percentage: 40 },
                ],
            },
        },
        {
            id: 'exit',
            type: 'exit',
            name: 'Exit workflow',
            description: 'The account completed the workflow.',
            config: { reason: 'Completed' },
        },
    ] as HogFlowAction[],
    edges: [
        { from: 'trigger', to: 'delay', type: 'continue' },
        { from: 'delay', to: 'webhook', type: 'continue' },
        { from: 'webhook', to: 'email', type: 'continue' },
        { from: 'email', to: 'conditional', type: 'continue' },
        { from: 'conditional', to: 'cohort', type: 'branch', index: 0 },
        { from: 'conditional', to: 'exit', type: 'branch', index: 1 },
        { from: 'conditional', to: 'exit', type: 'continue' },
        { from: 'cohort', to: 'exit', type: 'branch', index: 0 },
        { from: 'cohort', to: 'exit', type: 'branch', index: 1 },
        { from: 'cohort', to: 'exit', type: 'continue' },
    ],
}

type PanelStoryProps = {
    mode: HogFlowEditorMode
    selectedNodeId: string | null
    layout?: 'floating' | 'panel'
}

const meta: Meta<typeof HogFlowEditorPanel> = {
    title: 'Products/Workflows/Editor/Configuration panel',
    component: HogFlowEditorPanel,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_TRIGGER_VOLUME_ESTIMATE],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': PANEL_WORKFLOW,
                '/api/environments/:team_id/messaging_categories': { count: 0, results: [] },
                '/api/projects/:team_id/hog_function_templates': {
                    count: _hogFunctionTemplatesDestinations.results.length + 1,
                    results: [...(_hogFunctionTemplatesDestinations.results as unknown[]), EMAIL_TEMPLATE],
                },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => [
                    200,
                    { ...PANEL_WORKFLOW, ...((await request.json()) as Partial<HogFlow>) },
                ],
            },
            post: {
                '/api/environments/:team_id/hog_flows/user_blast_radius/': {
                    affected: 240,
                    total: 1200,
                    limit: 100000,
                    dedupe_key: null,
                    confirm_token: 'storybook-confirm-token',
                },
                '/api/environments/:team_id/query/:query_kind/': {
                    results: [
                        {
                            data: [120, 140, 180, 150, 130, 190, 170],
                            count: 1080,
                            labels: ['1-Sep', '2-Sep', '3-Sep', '4-Sep', '5-Sep', '6-Sep', '7-Sep'],
                        },
                    ],
                },
            },
        }),
    ],
}
export default meta

function PanelStory({ mode, selectedNodeId, layout = 'floating' }: PanelStoryProps): JSX.Element {
    const { originalWorkflow } = useValues(workflowLogic(LOGIC_PROPS))
    const { nodes } = useValues(hogFlowEditorLogic(LOGIC_PROPS))
    const { setWorkflowValues } = useActions(workflowLogic(LOGIC_PROPS))
    const { setMode, setSelectedNodeId } = useActions(hogFlowEditorLogic(LOGIC_PROPS))

    useEffect(() => {
        if (originalWorkflow) {
            setWorkflowValues(PANEL_WORKFLOW)
            setMode(mode)
        }
    }, [mode, originalWorkflow, setMode, setWorkflowValues])

    useEffect(() => {
        if (selectedNodeId === null || nodes.some((node) => node.id === selectedNodeId)) {
            setSelectedNodeId(selectedNodeId)
        }
    }, [nodes, selectedNodeId, setSelectedNodeId])

    return (
        <ReactFlowProvider>
            <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                <BindLogic logic={hogFlowEditorLogic} props={LOGIC_PROPS}>
                    {layout === 'panel' ? (
                        // Mirrors the tree view's host: a full-height row where the panel sits
                        // beside the tree, so the panel is as tall as the editor
                        <div className="@container/workflow-editor relative flex h-screen overflow-hidden @max-[48rem]/workflow-editor:flex-col @max-[48rem]/workflow-editor:overflow-y-auto">
                            <div className="min-w-0 flex-1 bg-background" />
                            <HogFlowEditorPanel layout="panel" />
                        </div>
                    ) : (
                        <div className="relative h-screen w-[37rem] overflow-hidden bg-surface-primary">
                            <HogFlowEditorPanel />
                        </div>
                    )}
                </BindLogic>
            </BindLogic>
        </ReactFlowProvider>
    )
}

const Template: StoryFn<PanelStoryProps> = (args) => <PanelStory {...args} />

export const Build: StoryFn<PanelStoryProps> = Template.bind({})
Build.args = { mode: 'build', selectedNodeId: 'delay' }

export const BuildPalette: StoryFn<PanelStoryProps> = Template.bind({})
BuildPalette.args = { mode: 'build', selectedNodeId: null }

export const Trigger: StoryFn<PanelStoryProps> = Template.bind({})
Trigger.args = { mode: 'build', selectedNodeId: 'trigger' }

export const Webhook: StoryFn<PanelStoryProps> = Template.bind({})
Webhook.args = { mode: 'build', selectedNodeId: 'webhook' }

export const Email: StoryFn<PanelStoryProps> = Template.bind({})
Email.args = { mode: 'build', selectedNodeId: 'email' }

export const EmailInSidePanel: StoryFn<PanelStoryProps> = Template.bind({})
EmailInSidePanel.args = { mode: 'build', selectedNodeId: 'email', layout: 'panel' }

export const ConditionalBranch: StoryFn<PanelStoryProps> = Template.bind({})
ConditionalBranch.args = { mode: 'build', selectedNodeId: 'conditional' }

export const CohortBranch: StoryFn<PanelStoryProps> = Template.bind({})
CohortBranch.args = { mode: 'build', selectedNodeId: 'cohort' }

export const Variables: StoryFn<PanelStoryProps> = Template.bind({})
Variables.args = { mode: 'variables', selectedNodeId: null }

export const Test: StoryFn<PanelStoryProps> = Template.bind({})
Test.args = { mode: 'test', selectedNodeId: 'delay' }

export const Metrics: StoryFn<PanelStoryProps> = Template.bind({})
Metrics.args = { mode: 'metrics', selectedNodeId: 'delay' }

export const Logs: StoryFn<PanelStoryProps> = Template.bind({})
Logs.args = { mode: 'logs', selectedNodeId: 'delay' }
