import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { makeReport } from '../../__mocks__/inboxMocks'
import { ImplementButton } from './ImplementButton'

const meta: Meta<typeof ImplementButton> = {
    title: 'Scenes-App/Inbox/ImplementButton',
    component: ImplementButton,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof ImplementButton>

const report = makeReport({ title: 'Exceptions spiked after the 18 June deploy' })

export const Default: Story = {
    render: () => <ImplementButton report={report} />,
}

export const Choices: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.Popover' } },
    render: () => <ImplementButton report={report} />,
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByLabelText('More implementation options'))
        await waitFor(() => {
            if (!document.querySelector('.Popover')) {
                throw new Error('implementation choices not open yet')
            }
        })
    },
}
