import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { TaskAssigneeFilterMenu } from './TaskAssigneeFilterMenu'

const meta: Meta<typeof TaskAssigneeFilterMenu> = {
    title: 'Products/PostHog AI/TaskAssigneeFilterMenu',
    component: TaskAssigneeFilterMenu,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': { results: [], count: 0 },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof TaskAssigneeFilterMenu>

export const Staff: Story = {}

export const NonStaff: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me/': { ...MOCK_DEFAULT_USER, is_staff: false },
            },
        }),
    ],
}
