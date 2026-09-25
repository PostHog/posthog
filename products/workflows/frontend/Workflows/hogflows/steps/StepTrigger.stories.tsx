import { Meta, StoryFn } from '@storybook/react'
import { Node } from '@xyflow/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { StepTriggerConfiguration } from './StepTrigger'

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }

const meta: Meta<typeof StepTriggerConfiguration> = {
    title: 'Products/Workflows/Steps/Trigger',
    component: StepTriggerConfiguration,
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/hog_flows/user_blast_radius/': {
                    affected: 1240,
                    total: 1240,
                    limit: 10000,
                    dedupe_key: null,
                },
            },
        }),
    ],
}
export default meta

const batchAction = {
    id: 'trigger_node',
    type: 'trigger',
    name: 'Trigger',
    description: '',
    config: { type: 'batch', filters: { properties: [] } },
} as TriggerAction

const Template: StoryFn<{ action: TriggerAction }> = ({ action }) => {
    const { setWorkflowInfo } = useActions(workflowLogic(LOGIC_PROPS))

    useEffect(() => {
        setWorkflowInfo({ actions: [action] })
    }, [action, setWorkflowInfo])

    return (
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <div className="w-[420px] p-4 flex flex-col gap-2">
                <StepTriggerConfiguration node={{ id: action.id, data: action } as Node<TriggerAction>} />
            </div>
        </BindLogic>
    )
}

export const BatchAudience: StoryFn<{ action: TriggerAction }> = Template.bind({})
BatchAudience.args = { action: batchAction }
