import { Meta, StoryFn } from '@storybook/react'

import { WorkflowSuggestionEmailChange } from './WorkflowSuggestionEmailChange'

const meta: Meta<typeof WorkflowSuggestionEmailChange> = {
    title: 'Products/Workflows/Suggestion email change',
    component: WorkflowSuggestionEmailChange,
    // Monaco lays the diff out after the first paint, like the other Monaco diff stories.
    tags: ['test-skip'],
}
export default meta

const email = (cta: string, buttonStyle = 'background:#1d4aff;color:#fff;padding:12px 20px'): string =>
    `<html><body><h1>Hi there,</h1><p>You finished setup. Here is one more thing to try before the week is out, and it only takes a minute.</p><p><a href="https://example.com" style="${buttonStyle}">${cta}</a></p><p>Thanks, the Example team</p></body></html>`

const Template: StoryFn<typeof WorkflowSuggestionEmailChange> = (args) => (
    <div className="max-w-200">
        <WorkflowSuggestionEmailChange {...args} />
    </div>
)

export const TextChange = Template.bind({})
TextChange.args = {
    change: {
        path: 'config.inputs.email.value.html',
        label: 'email › html',
        before: email('Run the play'),
        after: email('Create your first workflow'),
    },
}

export const StylingOnly = Template.bind({})
StylingOnly.args = {
    change: {
        path: 'config.inputs.email.value.html',
        label: 'email › html',
        before: email('Run the play'),
        after: email('Run the play', 'background:#1d4aff;color:#fff;padding:16px 28px;font-size:17px'),
    },
}
