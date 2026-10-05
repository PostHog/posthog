import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import type { Meta, StoryFn } from '@storybook/react'
import { ReactFlowProvider } from '@xyflow/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { HogFlowEditor } from '../HogFlowEditor'
import { hogFlowEditorLogic, HogFlowEditorMode } from '../hogFlowEditorLogic'
import { HogFlowEditorPanel } from '../panel/HogFlowEditorPanel'
import type { HogFlow, HogFlowAction } from '../types'
import { stepAiDecisionLogic } from './stepAiDecisionLogic'

const LOGIC_PROPS: WorkflowLogicProps = { id: 'storybook-ai-decision' }

const followUp = (id: string, name: string): HogFlowAction => ({
    id,
    type: 'delay',
    name,
    description: '',
    config: { delay_duration: '1h' },
})

const AI_DECISION_WORKFLOW: HogFlow = {
    ...NEW_WORKFLOW,
    id: LOGIC_PROPS.id!,
    name: 'AI decision examples',
    actions: [
        {
            id: 'trigger',
            type: 'trigger',
            name: 'Signed up',
            description: 'Start when someone signs up.',
            config: {
                type: 'event',
                filters: { events: [{ id: 'user signed up', name: 'user signed up', type: 'events' }] },
            },
        },
        {
            id: 'fit',
            type: 'ai_decision',
            name: 'Work account?',
            description: 'Check whether the signup looks like a real work account.',
            config: {
                question: 'Does this signup look like a real work account?',
                answer_type: 'yes_no',
                yes_means: 'A work email and a job title at a company',
                no_means: 'A personal email, a student, or a test signup',
                yes_threshold: 70,
                unsure_enabled: false,
                inputs: {
                    context: {
                        value: { email: '{person.properties.email}', job_title: '{person.properties.job_title}' },
                        templating: 'hog',
                    },
                },
            },
        },
        {
            id: 'track',
            type: 'ai_decision',
            name: 'Pick a track',
            description: 'Choose the onboarding track that fits.',
            config: {
                question: 'Which onboarding track fits this person best?',
                answer_type: 'pick_one',
                options: [
                    { name: 'Self-serve', description: 'Small teams who want to set things up on their own' },
                    { name: 'Sales-assisted', description: 'Larger companies that mention a contract or SSO' },
                    { name: 'Developer', description: 'Engineers who send events from code or ask about the API' },
                ],
                unsure_enabled: true,
                min_pick_probability: 60,
                inputs: {
                    context: {
                        value: { signup_answer: '{person.properties.signup_answer}', plan: '{event.properties.plan}' },
                        templating: 'hog',
                    },
                },
            },
        },
        followUp('self_serve', 'Self-serve guide'),
        followUp('sales', 'Sales follow-up'),
        followUp('developer', 'API quickstart'),
        followUp('review', 'Review by hand'),
        {
            id: 'exit',
            type: 'exit',
            name: 'Exit workflow',
            description: '',
            config: { reason: 'Completed' },
        },
    ] as HogFlowAction[],
    edges: [
        { from: 'trigger', to: 'fit', type: 'continue' },
        { from: 'fit', to: 'track', type: 'branch', index: 0 },
        { from: 'fit', to: 'exit', type: 'branch', index: 1 },
        { from: 'fit', to: 'exit', type: 'continue' },
        { from: 'track', to: 'self_serve', type: 'branch', index: 0 },
        { from: 'track', to: 'sales', type: 'branch', index: 1 },
        { from: 'track', to: 'developer', type: 'branch', index: 2 },
        { from: 'track', to: 'review', type: 'branch', index: 3 },
        { from: 'track', to: 'exit', type: 'continue' },
        { from: 'self_serve', to: 'exit', type: 'continue' },
        { from: 'sales', to: 'exit', type: 'continue' },
        { from: 'developer', to: 'exit', type: 'continue' },
        { from: 'review', to: 'exit', type: 'continue' },
    ],
}

const ANSWERED_TEST_RUN = {
    status: 'success',
    nextActionId: 'developer',
    execResult: {
        answer: 'Developer',
        probability: 0.78,
        probabilities: { 'Self-serve': 0.15, 'Sales-assisted': 0.07, Developer: 0.78 },
        model: 'example-model',
    },
}

const FAILED_TEST_RUN = {
    status: 'error',
    nextActionId: null,
    errors: ['Your organization is out of AI credits. Add credits in Billing, then try again.'],
}

const MOCKED_TEST_RUN = {
    status: 'success',
    nextActionId: 'self_serve',
    execResult: {
        answer: 'Self-serve',
        probabilities: { 'Self-serve': 1, 'Sales-assisted': 0, Developer: 0 },
        context: { signup_answer: 'Sending events from our Go backend and querying them with SQL.', plan: 'free' },
        context_bytes: 92,
    },
}

const meta: Meta = {
    title: 'Products/Workflows/Editor/AI decision',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_AI_DECISION],
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': AI_DECISION_WORKFLOW,
                '/api/environments/:team_id/messaging_categories': { count: 0, results: [] },
                '/api/projects/:team_id/hog_function_templates': { count: 0, results: [] },
                '/api/projects/:team_id/hog_flow_templates/': { count: 0, results: [] },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => [
                    200,
                    { ...AI_DECISION_WORKFLOW, ...((await request.json()) as Partial<HogFlow>) },
                ],
            },
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations/': async ({ request }) => {
                    const body = (await request.json()) as { mock_async_functions?: boolean }
                    return [200, body.mock_async_functions ? MOCKED_TEST_RUN : ANSWERED_TEST_RUN]
                },
            },
        }),
    ],
}
export default meta

type PanelStoryProps = {
    mode: HogFlowEditorMode
    selectedNodeId: string | null
    widthClassName?: string
    testRun?: 'person' | 'context'
}

function TestRunTrigger({ actionId, testRun }: { actionId: string; testRun: 'person' | 'context' }): null {
    const { config } = useValues(stepAiDecisionLogic({ workflowLogicProps: LOGIC_PROPS, actionId }))
    const { runPersonTest, loadContextPreview } = useActions(
        stepAiDecisionLogic({ workflowLogicProps: LOGIC_PROPS, actionId })
    )
    const hasConfig = !!config

    useEffect(() => {
        if (!hasConfig) {
            return
        }
        if (testRun === 'person') {
            runPersonTest()
        } else {
            loadContextPreview()
        }
    }, [hasConfig, testRun, runPersonTest, loadContextPreview])

    return null
}

function PanelStory({ mode, selectedNodeId, widthClassName = 'w-[37rem]', testRun }: PanelStoryProps): JSX.Element {
    const { originalWorkflow } = useValues(workflowLogic(LOGIC_PROPS))
    const { nodes } = useValues(hogFlowEditorLogic(LOGIC_PROPS))
    const { setWorkflowValues } = useActions(workflowLogic(LOGIC_PROPS))
    const { setMode, setSelectedNodeId } = useActions(hogFlowEditorLogic(LOGIC_PROPS))

    useEffect(() => {
        if (originalWorkflow) {
            setWorkflowValues(AI_DECISION_WORKFLOW)
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
                    <div className={`relative h-screen overflow-hidden bg-surface-primary ${widthClassName}`}>
                        <HogFlowEditorPanel />
                    </div>
                    {testRun && selectedNodeId && <TestRunTrigger actionId={selectedNodeId} testRun={testRun} />}
                </BindLogic>
            </BindLogic>
        </ReactFlowProvider>
    )
}

const Template: StoryFn<PanelStoryProps> = (args) => <PanelStory {...args} />

export const YesOrNo: StoryFn<PanelStoryProps> = Template.bind({})
YesOrNo.args = { mode: 'build', selectedNodeId: 'fit' }

export const PickOneWithUnsure: StoryFn<PanelStoryProps> = Template.bind({})
PickOneWithUnsure.args = { mode: 'build', selectedNodeId: 'track' }

// 32.5rem is the scene width left beside an open side panel in a 1280px window.
export const PickOneWithUnsureNarrow: StoryFn<PanelStoryProps> = Template.bind({})
PickOneWithUnsureNarrow.args = { mode: 'build', selectedNodeId: 'track', widthClassName: 'w-[32.5rem]' }

export const WhatIsSent: StoryFn<PanelStoryProps> = Template.bind({})
WhatIsSent.args = { mode: 'build', selectedNodeId: 'track', testRun: 'context' }

export const TestedWithAPerson: StoryFn<PanelStoryProps> = Template.bind({})
TestedWithAPerson.args = { mode: 'build', selectedNodeId: 'track', testRun: 'person' }

export const FailedTest: StoryFn<PanelStoryProps> = (args) => {
    useStorybookMocks({ post: { '/api/environments/:team_id/hog_flows/:id/invocations/': FAILED_TEST_RUN } })
    return <PanelStory {...args} />
}
FailedTest.args = { mode: 'build', selectedNodeId: 'track', testRun: 'person' }

export const MockedAnswerInTestPanel: StoryFn<PanelStoryProps> = Template.bind({})
MockedAnswerInTestPanel.args = { mode: 'test', selectedNodeId: 'track' }

export const Palette: StoryFn<PanelStoryProps> = Template.bind({})
Palette.args = { mode: 'build', selectedNodeId: null }

export const PaletteWithoutAiApproval: StoryFn<PanelStoryProps> = (args) => {
    useStorybookMocks({
        get: {
            '/api/organizations/@current/': { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false },
        },
    })
    return <PanelStory {...args} />
}
PaletteWithoutAiApproval.args = { mode: 'build', selectedNodeId: null }

export const Canvas: StoryFn = () => {
    const { originalWorkflow } = useValues(workflowLogic(LOGIC_PROPS))
    return (
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <div className="h-screen [&>div]:!h-full [&>div]:!max-h-none">
                {originalWorkflow && <HogFlowEditor key={originalWorkflow.id} isTreeView={false} />}
            </div>
        </BindLogic>
    )
}
Canvas.parameters = {
    testOptions: { waitForSelector: '.react-flow__node', viewport: { width: 1600, height: 1000 } },
}
