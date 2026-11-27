import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { MessagingCtaChip } from './MessagingCtaChip'

const meta: Meta<typeof MessagingCtaChip> = {
    title: 'Workflows/Messaging CTA/Chip',
    component: MessagingCtaChip,
    args: { placement: 'replay.player_chip' },
    parameters: {
        featureFlags: { [FEATURE_FLAGS.XPM_REPLAY_PLACEMENT]: 'player_chip' },
        testOptions: { waitForSelector: '[data-attr="messaging-cta-chip-replay.player_chip"]' },
    },
}
export default meta

type Story = StoryObj<typeof MessagingCtaChip>

export const PlayerChip: Story = {}

export const PlayerChipInANarrowBar: Story = {
    decorators: [
        (Story) => (
            <div className="flex w-40 flex-row items-center gap-1 border p-1 text-xs">
                <Story />
            </div>
        ),
    ],
}
