import type { Meta, StoryObj } from '@storybook/react'

import { PersonSearchMatchTags } from './PersonSearchMatchTags'

const meta: Meta<typeof PersonSearchMatchTags> = {
    title: 'Scenes-App/People/PersonSearchMatchTags',
    component: PersonSearchMatchTags,
    parameters: { layout: 'padded', viewMode: 'story' },
}

export default meta

type Story = StoryObj<typeof PersonSearchMatchTags>

export const EveryField: Story = {
    args: { matchedFields: ['distinct_id', 'email', 'name', 'id'] },
}
