import { Meta, StoryObj } from '@storybook/react'

import { LogsAlertDestinationSendApi } from 'products/logs/frontend/generated/api.schemas'

import { DestinationRecentSends } from './DestinationRecentSends'

const FIRING_FUNCTION = 'fn-firing'
const RESOLVED_FUNCTION = 'fn-resolved'

const SENDS: LogsAlertDestinationSendApi[] = [
    {
        hog_function_id: FIRING_FUNCTION,
        sent_at: '2023-02-18T09:40:00Z',
        path: 'native',
        succeeded: false,
        error: 'Webhook returned HTTP 500',
    },
    {
        hog_function_id: RESOLVED_FUNCTION,
        sent_at: '2023-02-18T09:20:00Z',
        path: 'native',
        succeeded: true,
        error: null,
    },
    {
        hog_function_id: FIRING_FUNCTION,
        sent_at: '2023-02-17T16:05:00Z',
        path: 'hog_function',
        succeeded: true,
        error: null,
    },
]

const meta: Meta<typeof DestinationRecentSends> = {
    title: 'Scenes-App/Logs/Alerts/Destination recent sends',
    component: DestinationRecentSends,
    parameters: { mockDate: '2023-02-18T10:00:00Z' },
    args: {
        sends: SENDS,
        loading: false,
        error: false,
        onRetry: () => {},
        eventLabelFor: (id: string) => (id === FIRING_FUNCTION ? 'Firing' : 'Resolved'),
    },
    render: (args) => (
        <div className="max-w-3xl p-4">
            <DestinationRecentSends {...args} />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof DestinationRecentSends>

export const BothPaths: Story = {}
export const Empty: Story = { args: { sends: [] } }
export const Loading: Story = { args: { sends: null, loading: true } }
export const Failed: Story = { args: { sends: null, error: true } }
