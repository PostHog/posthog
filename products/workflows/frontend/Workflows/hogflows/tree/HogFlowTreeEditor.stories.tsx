import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogFlow, HogFlowAction } from '../types'
import { HogFlowTreeEditor } from './HogFlowTreeEditor'

const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }

const actions = [
    {
        id: 'trigger',
        type: 'trigger',
        name: 'New ticket is created',
        description: 'Zendesk ticket created',
        config: { type: 'event', filters: {} },
    },
    {
        id: 'condition',
        type: 'conditional_branch',
        name: 'Check ticket priority',
        description: 'Route urgent tickets to the response team',
        config: {
            conditions: [
                { name: 'Priority is urgent', filters: {} },
                { name: 'Priority is high', filters: {} },
            ],
        },
    },
    {
        id: 'urgent-message',
        type: 'function',
        name: 'Notify the incident channel',
        description: 'Send a Slack message',
        config: { template_id: 'template-slack', inputs: {} },
    },
    {
        id: 'high-delay',
        type: 'delay',
        name: 'Wait 15 minutes',
        description: 'Give the assigned team time to respond',
        config: { delay_duration: '15m' },
    },
    {
        id: 'record-result',
        type: 'function',
        name: 'Record the routing result',
        description: 'Update the ticket',
        config: { template_id: 'template-webhook', inputs: {} },
    },
    {
        id: 'exit',
        type: 'exit',
        name: 'End workflow',
        description: 'The ticket has been routed',
        config: { reason: 'Completed' },
    },
] as HogFlowAction[]

const WORKFLOW: Pick<HogFlow, 'actions' | 'edges'> = {
    actions,
    edges: [
        { from: 'trigger', to: 'condition', type: 'continue' },
        { from: 'condition', to: 'urgent-message', type: 'branch', index: 0 },
        { from: 'condition', to: 'high-delay', type: 'branch', index: 1 },
        { from: 'condition', to: 'record-result', type: 'continue' },
        { from: 'urgent-message', to: 'record-result', type: 'continue' },
        { from: 'high-delay', to: 'record-result', type: 'continue' },
        { from: 'record-result', to: 'exit', type: 'continue' },
    ],
}

const meta: Meta<typeof HogFlowTreeEditor> = {
    title: 'Products/Workflows/Tree editor',
    component: HogFlowTreeEditor,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_LINEAR_VIEW],
    },
}
export default meta

const Template: StoryFn = () => {
    const { setWorkflowValues } = useActions(workflowLogic(LOGIC_PROPS))
    const { originalWorkflow } = useValues(workflowLogic(LOGIC_PROPS))

    useEffect(() => {
        if (originalWorkflow) {
            setWorkflowValues(WORKFLOW)
        }
    }, [originalWorkflow, setWorkflowValues])

    return (
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <BindLogic logic={hogFlowEditorLogic} props={LOGIC_PROPS}>
                <div className="flex h-[48rem] max-w-4xl overflow-hidden rounded border">
                    <HogFlowTreeEditor />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const BranchesRejoin: StoryFn = Template.bind({})
