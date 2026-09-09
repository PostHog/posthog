import { Meta, StoryObj } from '@storybook/react'

import { LemonDialog } from '@posthog/lemon-ui'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { testAccountFilterSettingsDialogProps } from './ScannerTriggers'

// The scanner wizard opens the internal-user-filtering setting in a dialog instead of navigating
// to project settings, so the unsaved draft stays mounted. This snapshots that dialog.
const meta: Meta<typeof LemonDialog> = {
    title: 'Scenes-App/Replay Vision/Test Account Filter Settings Dialog',
    component: LemonDialog,
    parameters: {
        layout: 'centered',
        mockDate: '2023-05-25',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof LemonDialog>

export const Default: Story = {
    render: () => <LemonDialog {...testAccountFilterSettingsDialogProps()} inline />,
}
