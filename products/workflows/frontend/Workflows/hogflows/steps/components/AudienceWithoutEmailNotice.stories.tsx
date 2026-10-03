import { Meta, StoryFn } from '@storybook/react'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { AudienceWithoutEmailNotice } from './AudienceWithoutEmailNotice'

const meta: Meta<typeof AudienceWithoutEmailNotice> = {
    title: 'Products/Workflows/Steps/Audience without email notice',
    component: AudienceWithoutEmailNotice,
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
