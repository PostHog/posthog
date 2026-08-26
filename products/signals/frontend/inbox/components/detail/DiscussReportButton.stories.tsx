import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { makeReport } from '../../__mocks__/inboxMocks'
import { DiscussReportButton } from './DiscussReportButton'

const meta: Meta<typeof DiscussReportButton> = {
    title: 'Scenes-App/Inbox/DiscussReportButton',
    component: DiscussReportButton,
    parameters: { layout: 'centered', testOptions: { snapshotTargetSelector: '.Popover' } },
}
export default meta

type Story = StoryObj<typeof DiscussReportButton>

// The popover is closed until the trigger is pressed, so each story opens it — otherwise every
// snapshot is of the same small button and the thing under review never renders. `findByText`
// rather than `getByText`: the trigger mounts a kea logic chain reaching organization and user
// state, so on a slow runner the play function can reach an empty canvas and fail the story.
const openPopover: Story['play'] = async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByText('Ask AI'))
    await waitFor(() => {
        if (!document.querySelector('.Popover')) {
            throw new Error('popover not open yet')
        }
    })
}

export const WithSuggestions: Story = {
    render: () => (
        <DiscussReportButton
            report={makeReport({
                title: 'Exceptions spiked after the 18 June deploy',
                suggested_prompts: [
                    'Which teams are hitting this exception the most?',
                    'Did the error rate change after the 18 June deploy?',
                    'Is anything else in the checkout flow failing at the same time?',
                ],
            })}
            reportUrl="https://app.posthog.com/project/1/inbox/report-1"
        />
    ),
    play: openPopover,
}

/** A pipeline report, and every report written before suggestions existed. Must look untouched. */
export const WithoutSuggestions: Story = {
    render: () => (
        <DiscussReportButton
            report={makeReport({ title: 'Exceptions spiked after the 18 June deploy' })}
            reportUrl="https://app.posthog.com/project/1/inbox/report-1"
        />
    ),
    play: openPopover,
}
