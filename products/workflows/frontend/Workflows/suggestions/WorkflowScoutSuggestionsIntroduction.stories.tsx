import { Meta, StoryFn } from '@storybook/react'

import { LemonSwitch } from '@posthog/lemon-ui'

import { WorkflowScoutSuggestionsIntroduction } from './WorkflowScoutSuggestionsIntroduction'

const meta: Meta<typeof WorkflowScoutSuggestionsIntroduction> = {
    title: 'Products/Workflows/Scout suggestions introduction',
    component: WorkflowScoutSuggestionsIntroduction,
}
export default meta

const Template: StoryFn<typeof WorkflowScoutSuggestionsIntroduction> = ({ enabled }) => (
    <div className="@container/main-content w-200">
        <WorkflowScoutSuggestionsIntroduction
            enabled={enabled}
            toggle={<LemonSwitch bordered label="Suggest improvements" checked={enabled} onChange={() => {}} />}
        />
    </div>
)

export const Off = Template.bind({})
Off.args = { enabled: false }

export const On = Template.bind({})
On.args = { enabled: true }
