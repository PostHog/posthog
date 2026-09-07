import type { Meta, StoryFn } from '@storybook/react'
import { ReactFlowProvider } from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic, HogFlowEditorMode } from '../hogFlowEditorLogic'
import type { HogFlow, HogFlowAction } from '../types'
import { HogFlowEditorPanel } from './HogFlowEditorPanel'

const LOGIC_PROPS: WorkflowLogicProps = { id: 'storybook-configuration-panel' }

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
            config: { type: 'event', filters: {} },
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
        { from: 'webhook', to: 'conditional', type: 'continue' },
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
}

const meta: Meta<typeof HogFlowEditorPanel> = {
    title: 'Products/Workflows/Editor/Configuration panel',
    component: HogFlowEditorPanel,
    parameters: {
        layout: 'fullscreen',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': PANEL_WORKFLOW,
                '/api/environments/:team_id/messaging_categories': { count: 0, results: [] },
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
            },
        }),
    ],
}
export default meta

function PanelStory({ mode, selectedNodeId }: PanelStoryProps): JSX.Element {
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
                    <div className="relative h-screen w-[37rem] overflow-hidden bg-surface-primary">
                        <HogFlowEditorPanel />
                    </div>
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

export const Webhook: StoryFn<PanelStoryProps> = Template.bind({})
Webhook.args = { mode: 'build', selectedNodeId: 'webhook' }

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
