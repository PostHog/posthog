import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { SCOUT_TOOL_CATALOGUE } from './scoutToolFixtures'
import { ScoutToolsPicker } from './ScoutToolsPicker'

const meta: Meta<typeof ScoutToolsPicker> = {
    title: 'Scenes-App/Inbox/ScoutToolsPicker',
    component: ScoutToolsPicker,
    args: { scoutName: 'Dashboard hygiene', savedTools: null, onSave: () => {}, onClose: () => {} },
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/scout/configs/tool_catalogue/': () => [200, SCOUT_TOOL_CATALOGUE],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ScoutToolsPicker>

/** A scout that can call every tool, about to get its first list. The write access panel reads "Read only". */
export const NewList: Story = {}

/** A saved list with write tools, so the panel names the write access the list gives. */
export const SavedListWithWriteTools: Story = {
    args: { savedTools: ['dashboard-get', 'dashboard-update', 'insight-create', 'insight-get'] },
}
