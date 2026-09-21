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
    args: {
        person: {
            id: '0198f3c1-6c2a-7a5b-9d41-9a1b2c3d4e5f',
            distinct_ids: ['abe@example.com'],
            properties: { email: 'abe@example.com', name: 'Abe Example' },
            matched_fields: ['distinct_id', 'email', 'name', 'id'],
        },
    },
}
