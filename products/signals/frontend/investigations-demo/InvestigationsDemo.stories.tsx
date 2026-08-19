import type { Meta, StoryObj } from '@storybook/react'

import { InvestigationsFocusScene } from './InvestigationsFocusScene'
import { InvestigationsInboxScene } from './InvestigationsInboxScene'
import { InvestigationsMonitorScene } from './InvestigationsMonitorScene'
import { InvestigationsReportScene } from './InvestigationsReportScene'
import { InvestigationsResolvedScene } from './InvestigationsResolvedScene'

// Mock-data redesign preview of the investigations inbox. Every scene renders
// straight from products/signals/frontend/investigations-demo/mockData.ts, so
// no API mocks are needed.

const meta: Meta = {
    title: 'Scenes-App/Investigations demo',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj

export const Inbox: Story = { render: () => <InvestigationsInboxScene /> }

export const FocusMode: Story = {
    render: () => (
        <div className="h-screen">
            <InvestigationsFocusScene />
        </div>
    ),
}

export const Report: Story = { render: () => <InvestigationsReportScene /> }

export const Resolved: Story = { render: () => <InvestigationsResolvedScene /> }

export const Monitor: Story = { render: () => <InvestigationsMonitorScene /> }
