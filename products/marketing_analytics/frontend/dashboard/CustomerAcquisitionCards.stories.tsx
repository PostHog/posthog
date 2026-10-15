import { Meta, StoryObj } from '@storybook/react'

import { CustomerAcquisitionCards } from './CustomerAcquisitionCards'

const meta: Meta<typeof CustomerAcquisitionCards> = {
    title: 'Marketing Analytics/Customer acquisition cards',
    component: CustomerAcquisitionCards,
    decorators: [
        (Story) => (
            <div className="grid w-160 max-w-full grid-cols-2 gap-2">
                <Story />
            </div>
        ),
    ],
    args: {
        configurationLoading: false,
        configured: true,
        loading: false,
        error: false,
        customerResults: [{ key: 'unique conversions', kind: 'unit', value: 20, previous: 10 }],
        trafficResults: [{ key: 'visitors', kind: 'unit', value: 100, previous: 100 }],
        onConfigure: () => {},
        onRetry: () => {},
    },
}

export default meta
type Story = StoryObj<typeof CustomerAcquisitionCards>

export const Configured: Story = {}
export const Unconfigured: Story = { args: { configured: false } }
export const Loading: Story = {
    args: { loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const ConfigurationLoading: Story = {
    args: { configurationLoading: true, configured: false },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Error: Story = { args: { error: true } }
export const NoCustomers: Story = {
    args: { customerResults: [{ key: 'unique conversions', kind: 'unit', value: 0, previous: 0 }] },
}
