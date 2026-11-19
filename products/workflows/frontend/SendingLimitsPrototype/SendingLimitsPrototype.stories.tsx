// PROTOTYPE (branch prototype/sending-limits-ux): throwaway, never merge.
import { Meta, StoryFn } from '@storybook/react'

import { SendingLimitsPrototype } from './SendingLimitsPrototype'

const meta: Meta = {
    title: 'Prototypes/Workflows/Sending limits',
    parameters: {
        layout: 'fullscreen',
        // After the Nov 3, 2026 email metrics incident leaves the 30-day window, so its banner stays out.
        mockDate: '2026-12-10 12:00:00',
    },
    tags: ['test-skip'],
}
export default meta

export const SendingLimits: StoryFn = () => <SendingLimitsPrototype />
