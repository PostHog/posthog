import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { IconPullRequest } from '@posthog/icons'

import { makeReport } from '../../__mocks__/inboxMocks'
import { CreatePrReportButton } from './CreatePrReportButton'
import { ReportDetailAction } from './ReportDetailActions'

const ACTION: ReportDetailAction = {
    key: 'create-pr',
    label: 'Create PR',
    icon: <IconPullRequest />,
    tooltip: 'Have Self-driving open a pull request for this report',
    onClick: () => {},
}

const meta: Meta<typeof CreatePrReportButton> = {
    title: 'Scenes-App/Inbox/CreatePrReportButton',
    component: CreatePrReportButton,
    parameters: { layout: 'centered', testOptions: { snapshotTargetSelector: '.Popover' } },
}
export default meta

type Story = StoryObj<typeof CreatePrReportButton>

// The popover is closed until the trigger is pressed, so the story opens it — otherwise the snapshot
// is of the same small button and the note field never renders. `findByText` rather than `getByText`:
// the trigger mounts a kea logic chain reaching organization and user state, so on a slow runner the
// play function can reach an empty canvas and fail the story.
const openPopover: Story['play'] = async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByText('Create PR'))
    await waitFor(() => {
        if (!document.querySelector('.Popover')) {
            throw new Error('popover not open yet')
        }
    })
}

export const Default: Story = {
    render: () => (
        <CreatePrReportButton
            report={makeReport({ title: 'Exceptions spiked after the 18 June deploy' })}
            action={ACTION}
        />
    ),
    play: openPopover,
}
