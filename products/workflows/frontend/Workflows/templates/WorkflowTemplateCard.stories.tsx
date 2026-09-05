import './WorkflowTemplateChooser.scss'

import { Meta, StoryFn } from '@storybook/react'

import type { HogFlowAction, HogFlowTemplate } from '../hogflows/types'
import { WorkflowTemplateAiBadge } from './WorkflowTemplateAiBadge'
import { WorkflowTemplateBlankPreview } from './WorkflowTemplateBlankPreview'
import { WorkflowTemplateCard, WorkflowTemplateCardProps } from './WorkflowTemplateCard'
import { isAiTemplate } from './workflowTemplateDisplay'
import { WorkflowTemplateMeta } from './WorkflowTemplateMeta'
import { WorkflowTemplateSteps } from './WorkflowTemplateSteps'

const meta: Meta<typeof WorkflowTemplateCard> = {
    title: 'Products/Workflows/Template card',
    component: WorkflowTemplateCard,
}
export default meta

type StepSpec = HogFlowAction['type'] | [HogFlowAction['type'], string]

function template(
    name: string,
    description: string,
    trigger: string,
    steps: StepSpec[],
    tags: string[] = []
): HogFlowTemplate {
    const actions = [
        { id: 'trigger', type: 'trigger', name: 'Trigger', config: { type: trigger, filters: {} } },
        ...steps.map((step, index) => {
            const [type, templateId] = Array.isArray(step) ? step : [step, undefined]
            return { id: `${type}_${index}`, type, name: type, config: templateId ? { template_id: templateId } : {} }
        }),
        { id: 'exit', type: 'exit', name: 'Exit', config: {} },
    ]
    return { id: name, name, description, actions, tags, scope: 'global' } as unknown as HogFlowTemplate
}

// Copied from the templates that ship in products/workflows/backend/templates, so the card is
// measured against the copy people actually see
const TEMPLATES: HogFlowTemplate[] = [
    template(
        'New support ticket notification',
        'Notify your support team in Slack as soon as a new ticket comes in.',
        'event',
        [['function', 'template-slack']],
        ['slack', 'support ticket', 'support']
    ),
    template(
        'Welcome email sequence',
        'Welcome new signups with an intro email, then check in on how they are getting on.',
        'event',
        [['function_email', 'template-email'], 'delay', ['function_email', 'template-email']]
    ),
    template(
        'Educate users for unused features',
        'Find people who have not tried an important feature yet, and send them a tip that gets them started.',
        'schedule',
        [
            'delay',
            'conditional_branch',
            ['function_email', 'template-email'],
            'delay',
            'conditional_branch',
            ['function_email', 'template-email'],
        ],
        ['product usage']
    ),
    template(
        'Notify sales for high intent users',
        'Alert your sales team in Slack when someone shows strong buying intent, so they can follow up while it is warm.',
        'event',
        ['conditional_branch', ['function', 'template-slack']],
        ['sales', 'slack']
    ),
    // Stands in for the AI template on the way, so the badge has something to sit on
    template(
        'Triage a new error with an agent',
        'Hand a new error to an AI agent. It reads the stack trace, finds the change that caused it, and opens a draft pull request.',
        'internal-event',
        [['function', 'template-posthog-create-task']],
        ['error tracking']
    ),
    template(
        'Trial started → upgrade nudge',
        'Nudge trial users to upgrade when they show real usage, instead of when the clock runs down.',
        'event',
        [
            'conditional_branch',
            ['function_email', 'template-email'],
            'conditional_branch',
            ['function_email', 'template-email'],
            'conditional_branch',
            'delay',
            ['function_email', 'template-email'],
            'delay',
        ]
    ),
    template(
        'Announce a new feature',
        'Tell people about a new feature, but only the ones who can actually use it.',
        'event',
        [
            'conditional_branch',
            ['function_email', 'template-email'],
            'conditional_branch',
            ['function_email', 'template-email'],
            'delay',
        ]
    ),
    template(
        'Send a webhook when a user upgrades',
        'Send a webhook when someone upgrades, so your CRM, billing tool, or backend can react.',
        'event',
        [['function', 'template-webhook']],
        ['webhook', 'upgrade']
    ),
]

function templateArgs(source: HogFlowTemplate): WorkflowTemplateCardProps {
    return {
        name: source.name,
        description: source.description,
        preview: <WorkflowTemplateSteps actions={source.actions} />,
        badge: isAiTemplate(source) ? <WorkflowTemplateAiBadge /> : null,
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
    <div className="w-[26rem]">
        <WorkflowTemplateCard {...props} />
    </div>
)

export const Basic: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
Basic.args = templateArgs(TEMPLATES[1])

// The longest description that ships, next to the menu a team template shows
export const LongestDescription: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
LongestDescription.args = { ...templateArgs(TEMPLATES[3]), onEdit: () => {}, onDelete: () => {} }

// A template that hands work to an agent, so the AI badge shows
export const Ai: StoryFn = () => (
    <div className="w-[26rem]">
        <WorkflowTemplateCard {...templateArgs(TEMPLATES[4])} />
    </div>
)

export const Blank: StoryFn<WorkflowTemplateCardProps> = Template.bind({})
Blank.args = BLANK_ARGS

// The picker drops to one column in a narrow modal, so the card has to hold up at this width
export const Narrow: StoryFn = () => (
    <div className="w-64">
        <WorkflowTemplateCard {...templateArgs(TEMPLATES[3])} />
    </div>
)

// The picker's own layout: columns, so a long description makes one card taller and nothing else
export const Picker: StoryFn = () => (
    <div className="WorkflowTemplateChooser w-[54rem]">
        <WorkflowTemplateCard {...BLANK_ARGS} />
        {TEMPLATES.map((source) => (
            <WorkflowTemplateCard key={source.id} {...templateArgs(source)} />
        ))}
    </div>
)
