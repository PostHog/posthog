import type { Meta, StoryObj } from '@storybook/react'

import type { PersonType } from '~/types'

import { PersonSearchMatchTags } from './PersonSearchMatchTags'

const meta: Meta<typeof PersonSearchMatchTags> = {
    title: 'Scenes-App/People/PersonSearchMatchTags',
    component: PersonSearchMatchTags,
    parameters: { layout: 'padded', viewMode: 'story' },
}

export default meta

type Story = StoryObj<typeof PersonSearchMatchTags>

function searchResult(matched_fields: PersonType['matched_fields']): PersonType {
    return {
        id: '0198f3c1-6c2a-7a5b-9d41-9a1b2c3d4e5f',
        distinct_ids: ['abe@example.com'],
        properties: { email: 'abe@example.com', name: 'Abe Example' },
        matched_fields,
    }
}

// The same row shape as a taxonomic filter result: the name truncates and the tags keep their width.
function pickerRow(width: string): Story['decorators'] {
    return [
        (Story, { args }) => (
            <div className={`flex items-center gap-2 rounded border p-2 ${width}`}>
                <span className="truncate">{args.person.properties.email}</span>
                <span className="flex shrink-0 ml-auto pl-2 empty:hidden">
                    <Story />
                </span>
            </div>
        ),
    ]
}

export const OneField: Story = {
    args: { person: searchResult(['email']) },
}

export const EveryField: Story = {
    args: { person: searchResult(['distinct_id', 'email', 'name', 'id']) },
}

export const NoMatchedFieldInARow: Story = {
    args: { person: searchResult([]) },
    decorators: pickerRow('w-[320px]'),
}

export const EveryFieldInANarrowRow: Story = {
    args: { person: searchResult(['distinct_id', 'email', 'name', 'id']) },
    decorators: pickerRow('w-[240px]'),
}
