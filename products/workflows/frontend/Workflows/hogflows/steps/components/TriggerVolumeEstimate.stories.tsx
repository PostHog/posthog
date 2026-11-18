import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import { HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH } from '../../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../../types'
import { TriggerVolumeEstimate } from './TriggerVolumeEstimate'

const DAILY_COUNTS = [820, 910, 1150, 1040, 980, 1310, 1220]

const TRIGGER_ACTION = {
    id: 'trigger',
    type: 'trigger',
    name: 'Pageview',
    description: '',
    config: { type: 'event', filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events' }] } },
} as HogFlowAction

const AI_TASK_ACTION = {
    id: 'ai_task',
    type: 'function',
    name: 'Create AI task',
    description: '',
    config: { template_id: 'template-posthog-create-task', inputs: {} },
} as HogFlowAction

const EVENT_TRIGGER_WORKFLOW_ID = 'storybook-trigger-volume'
const AI_TASK_WORKFLOW_ID = 'storybook-trigger-volume-ai-task'

const WORKFLOWS: Record<string, HogFlow> = {
    [EVENT_TRIGGER_WORKFLOW_ID]: {
        ...NEW_WORKFLOW,
        id: EVENT_TRIGGER_WORKFLOW_ID,
        name: 'Welcome email',
        actions: [TRIGGER_ACTION],
    } as HogFlow,
    [AI_TASK_WORKFLOW_ID]: {
        ...NEW_WORKFLOW,
        id: AI_TASK_WORKFLOW_ID,
        name: 'Triage every pageview',
        actions: [TRIGGER_ACTION, AI_TASK_ACTION],
    } as HogFlow,
}

const meta: Meta<typeof TriggerVolumeEstimate> = {
    title: 'Products/Workflows/Steps/Trigger volume',
    component: TriggerVolumeEstimate,
    decorators: [
        mswDecorator({
            get: {
                // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
                '/api/environments/:team_id/hog_flows/:id/': ({ params }) => [
                    200,
                    WORKFLOWS[String(params.id)] ?? WORKFLOWS[EVENT_TRIGGER_WORKFLOW_ID],
                ],
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': {
                    results: [
                        {
                            data: DAILY_COUNTS,
                            count: DAILY_COUNTS.reduce((sum, value) => sum + value, 0),
                            labels: ['1-Sep', '2-Sep', '3-Sep', '4-Sep', '5-Sep', '6-Sep', '7-Sep'],
                        },
                    ],
                },
            },
        }),
    ],
}
export default meta

const Template: StoryFn<{ id: string; width: number }> = ({ id, width }) => {
    const logicProps: WorkflowLogicProps = { id }

    return (
        <BindLogic logic={workflowLogic} props={logicProps}>
            {/* Pinned to the panel's width, minus its own px-2, so the chart is as wide as it is in the app */}
            <div className="px-2" style={{ width }}>
                <TriggerVolumeEstimate action={TRIGGER_ACTION} />
            </div>
        </BindLogic>
    )
}

export const EventTrigger: StoryFn<{ id: string; width: number }> = Template.bind({})
EventTrigger.args = { id: EVENT_TRIGGER_WORKFLOW_ID, width: HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH }

export const OverTheAiTaskLimit: StoryFn<{ id: string; width: number }> = Template.bind({})
OverTheAiTaskLimit.args = { id: AI_TASK_WORKFLOW_ID, width: HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH }
