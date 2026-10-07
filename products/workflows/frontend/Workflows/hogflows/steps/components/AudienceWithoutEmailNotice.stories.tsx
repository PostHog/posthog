import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { AudienceWithoutEmailNotice } from './AudienceWithoutEmailNotice'

const meta: Meta<typeof AudienceWithoutEmailNotice> = {
    title: 'Products/Workflows/Steps/Audience without email notice',
    component: AudienceWithoutEmailNotice,
    parameters: { featureFlags: [FEATURE_FLAGS.WORKFLOWS_MISSING_EMAIL_WARNING] },
}
export default meta

const Template: StoryFn<typeof AudienceWithoutEmailNotice> = (args) => (
    <div className="max-w-120">
        <AudienceWithoutEmailNotice {...args} />
    </div>
)

export const ManyPeople: StoryFn<typeof AudienceWithoutEmailNotice> = Template.bind({})
ManyPeople.args = {
    withoutEmail: 1342,
    audienceProperties: [
        { key: 'plan', type: PropertyFilterType.Person, value: ['pro'], operator: PropertyOperator.Exact },
    ] as AnyPropertyFilter[],
}

export const OnePerson: StoryFn<typeof AudienceWithoutEmailNotice> = Template.bind({})
OnePerson.args = { withoutEmail: 1, audienceProperties: [] }
