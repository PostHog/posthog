import { Meta, StoryFn } from '@storybook/react'

import type { HogFlowAction, HogFlowTemplate } from '../hogflows/types'
import { WorkflowTemplateBlankPreview } from './WorkflowTemplateBlankPreview'
import { WorkflowTemplateCard, WorkflowTemplateCardProps } from './WorkflowTemplateCard'
import { WorkflowTemplateMeta } from './WorkflowTemplateMeta'
import { WorkflowTemplateSteps } from './WorkflowTemplateSteps'

const meta: Meta<typeof WorkflowTemplateCard> = {
    title: 'Products/Workflows/Template card',
    component: WorkflowTemplateCard,
}
export default meta

function action(id: string, type: HogFlowAction['type'], config: Record<string, any> = {}): HogFlowAction {
    return { id, type, name: id, config } as HogFlowAction
}

function template(name: string, description: string, actions: HogFlowAction[], scope = 'global'): HogFlowTemplate {
    return { id: name, name, description, actions, scope, tags: [] } as unknown as HogFlowTemplate
}

const WELCOME_EMAIL = template('Welcome email', 'Send one welcome email when a person signs up.', [
    action('trigger', 'trigger', { type: 'event', filters: {} }),
    action('email', 'function_email'),
    action('exit', 'exit'),
])

const ONBOARDING_SERIES = template(
    'Onboarding series with a very long name that has to truncate',
    'Guide new people through their first week with a series of emails, a wait step, and an SMS reminder for anyone who has not finished setup.',
    [
        action('trigger', 'trigger', { type: 'schedule' }),
        action('delay', 'delay', { delay_duration: '1d' }),
        action('branch', 'conditional_branch', { conditions: [] }),
        action('email', 'function_email'),
        action('wait', 'wait_until_condition'),
        action('sms', 'function_sms'),
        action('exit', 'exit'),
    ],
    'team'
)

function templateArgs(source: HogFlowTemplate): WorkflowTemplateCardProps {
    return {
        name: source.name,
        description: source.description,
        preview: <WorkflowTemplateSteps actions={source.actions} />,
        footer: <WorkflowTemplateMeta template={source} />,
        onClick: () => {},
        'data-attr': 'create-workflow-from-template',
    }
}

const BLANK_ARGS: WorkflowTemplateCardProps = {
    name: 'Blank workflow',
    description: 'Start from scratch and add your own trigger and steps.',
    preview: <WorkflowTemplateBlankPreview />,
    footer: null,
    onClick: () => {},
    'data-attr': 'create-workflow-blank',
}

const Template: StoryFn<WorkflowTemplateCardProps> = (props) => (
    <div className="w-[24rem]">
        <WorkflowTemplateCard {...props} />
    </div>
)

export const Basic: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
Basic.args = templateArgs(WELCOME_EMAIL)

export const ManySteps: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
ManySteps.args = { ...templateArgs(ONBOARDING_SERIES), onEdit: () => {}, onDelete: () => {} }

export const Blank: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
Blank.args = BLANK_ARGS

// The picker collapses to one column in a narrow modal, so the card has to hold up at this width
export const Narrow: StoryFn = () => (
    <div className="w-64">
        <WorkflowTemplateCard {...templateArgs(ONBOARDING_SERIES)} />
    </div>
)

// In the picker the cards sit in a grid, where they all take the height of the tallest one
export const Grid: StoryFn = () => (
    <div className="grid grid-cols-2 gap-2 items-stretch w-[50rem]">
        <WorkflowTemplateCard {...BLANK_ARGS} />
        <WorkflowTemplateCard {...templateArgs(WELCOME_EMAIL)} />
        <WorkflowTemplateCard {...templateArgs(ONBOARDING_SERIES)} />
    </div>
)
