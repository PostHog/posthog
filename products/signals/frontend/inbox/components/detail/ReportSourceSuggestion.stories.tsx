import type { Meta, StoryObj } from '@storybook/react'

import { makeReport } from '../../__mocks__/inboxMocks'
import { ReportSourceSuggestion } from './ReportSourceSuggestion'

const meta: Meta<typeof ReportSourceSuggestion> = {
    title: 'Scenes-App/Inbox/ReportSourceSuggestion',
    component: ReportSourceSuggestion,
    parameters: { layout: 'centered' },
    decorators: [
        (Story): JSX.Element => (
            <div className="w-96 max-w-full">
                <Story />
            </div>
        ),
    ],
    args: {
        report: makeReport({ title: 'Checkout requests time out' }),
        suggestion: {
            product: 'logs',
            reason: 'Logs from the checkout service could show whether the timeout starts at the payment provider.',
        },
    },
}
export default meta

type Story = StoryObj<typeof ReportSourceSuggestion>

export const Logs: Story = {}
