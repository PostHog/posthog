import type { Meta, StoryObj } from '@storybook/react'

import { RequestUsageSummaryCard } from './RequestUsageSummaryCard'

const meta: Meta<typeof RequestUsageSummaryCard> = {
    title: 'Scenes-App/Feature Flags/Request Usage Summary Card',
    component: RequestUsageSummaryCard,
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<typeof RequestUsageSummaryCard>

export const BillingUnits: Story = {
    args: { label: 'Billing units', value: 123456 },
}
