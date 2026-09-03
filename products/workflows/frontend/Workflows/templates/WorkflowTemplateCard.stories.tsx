import { Meta, StoryFn } from '@storybook/react'

import type { HogFlowAction } from '../hogflows/types'
import { WorkflowTemplateBlankPreview } from './WorkflowTemplateBlankPreview'
import { WorkflowTemplateCard, WorkflowTemplateCardProps } from './WorkflowTemplateCard'
import { WorkflowTemplateSteps } from './WorkflowTemplateSteps'

const meta: Meta<typeof WorkflowTemplateCard> = {
    title: 'Products/Workflows/Template card',
    component: WorkflowTemplateCard,
}
export default meta

function action(id: string, type: HogFlowAction['type'], config: Record<string, any> = {}): HogFlowAction {
    return { id, type, name: id, config } as HogFlowAction
}

const SHORT_FLOW: HogFlowAction[] = [
    action('trigger', 'trigger', { type: 'event', filters: {} }),
    action('email', 'function_email'),
    action('exit', 'exit'),
]

const LONG_FLOW: HogFlowAction[] = [
    action('trigger', 'trigger', { type: 'event', filters: {} }),
    action('delay', 'delay', { delay_duration: '1d' }),
    action('branch', 'conditional_branch', { conditions: [] }),
    action('email', 'function_email'),
    action('wait', 'wait_until_condition'),
    action('sms', 'function_sms'),
    action('exit', 'exit'),
]

const Template: StoryFn<WorkflowTemplateCardProps> = (props) => (
    <div className="w-64">
        <WorkflowTemplateCard {...props} />
    </div>
)

export const Basic: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
Basic.args = {
    name: 'Welcome email',
    description: 'Send one welcome email when a person signs up.',
    preview: <WorkflowTemplateSteps actions={SHORT_FLOW} />,
    footer: <span className="text-xs text-tertiary">Starts on an event</span>,
    onClick: () => {},
    'data-attr': 'create-workflow-from-template',
}

export const ManySteps: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
ManySteps.args = {
    ...Basic.args,
    name: 'Onboarding series with a very long name that has to truncate',
    description:
        'Guide new people through their first week with a series of emails, a wait step, and an SMS reminder for anyone who has not finished setup.',
    preview: <WorkflowTemplateSteps actions={LONG_FLOW} />,
    onEdit: () => {},
    onDelete: () => {},
}

export const Blank: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
Blank.args = {
    name: 'Blank workflow',
    description: 'Start from scratch and add your own trigger and steps.',
    preview: <WorkflowTemplateBlankPreview />,
    footer: null,
    onClick: () => {},
    'data-attr': 'create-workflow-blank',
}

// The picker lays the cards out in a grid, where they all take the height of the tallest one.
export const Grid: StoryFn = () => (
    <div className="grid grid-cols-3 gap-2 items-stretch w-[46rem]">
        <WorkflowTemplateCard {...(Blank.args as WorkflowTemplateCardProps)} />
        <WorkflowTemplateCard {...(Basic.args as WorkflowTemplateCardProps)} />
        <WorkflowTemplateCard {...(ManySteps.args as WorkflowTemplateCardProps)} />
    </div>
)
