import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { IssueSceneStatusSelect } from './IssueSceneStatusSelect'

const meta: Meta<typeof IssueSceneStatusSelect> = {
    title: 'Scenes-App/ErrorTracking/IssueSceneStatusSelect',
    component: IssueSceneStatusSelect,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.ERROR_TRACKING_RESOLVE_IN_NEXT_RELEASE],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof IssueSceneStatusSelect>

export const ResolvedInTheNextReleaseAndStillSeen: Story = {
    args: {
        status: 'resolved',
        resolvedUntil: 'new_release',
        stillSeen: true,
        latestRelease: {
            id: '0198c7e4-0000-0000-0000-000000000001',
            version: '2.4.0',
            project: 'web',
            created_at: '2026-01-01T12:00:00Z',
        },
        onChange: () => {},
    },
}
