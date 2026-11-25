import type { Meta, StoryObj } from '@storybook/react'

import { IssueSceneStatusSelect } from './IssueSceneStatusSelect'

const meta: Meta<typeof IssueSceneStatusSelect> = {
    title: 'Scenes-App/ErrorTracking/IssueSceneStatusSelect',
    component: IssueSceneStatusSelect,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof IssueSceneStatusSelect>

export const ResolvedUntilANewRelease: Story = {
    args: {
        status: 'resolved',
        resolvedUntil: 'new_release',
        latestRelease: {
            id: '0198c7e4-0000-0000-0000-000000000001',
            version: '2.4.0',
            project: 'web',
            created_at: '2026-01-01T12:00:00Z',
        },
        onChange: () => {},
    },
}
