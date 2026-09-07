import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { makeReport } from '../../__mocks__/inboxMocks'
import { CreatePrButton } from './CreatePrButton'

const meta: Meta<typeof CreatePrButton> = {
    title: 'Scenes-App/Inbox/CreatePrButton',
    component: CreatePrButton,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof CreatePrButton>

const report = makeReport({ title: 'Exceptions spiked after the 18 June deploy' })

/** The resting split button. The divider is the only cue that the chevron does something else. */
export const Default: Story = {
    render: () => <CreatePrButton report={report} />,
}

// The note box is closed until the chevron is pressed, so the story opens it. `findByLabelText`
// rather than `getByLabelText`: the button mounts a kea logic chain reaching organization and user
// state, so on a slow runner the play function can reach an empty canvas and fail the story.
export const Steering: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.Popover' } },
    render: () => <CreatePrButton report={report} />,
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('Add direction for the agent'))
        await waitFor(() => {
            if (!document.querySelector('.Popover')) {
                throw new Error('note box not open yet')
            }
        })
    },
}
