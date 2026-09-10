import type { Meta, StoryObj } from '@storybook/react'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { mockLargeScoutFleet } from '../../../__mocks__/scoutConfigs'
import { ScoutOwners } from './ScoutOwners'

// The four states the scout page's identity line can be in. A canonical scout renders nothing,
// which is the row that should stay blank.

function scout(id: string): SignalScoutConfigApi {
    const config = mockLargeScoutFleet.find((candidate) => candidate.id === id)
    if (!config) {
        throw new Error(`No mock scout with id ${id}`)
    }
    return config
}

const meta: Meta<typeof ScoutOwners> = {
    title: 'Scenes-App/Inbox/ScoutOwners',
    component: ScoutOwners,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-06-11' },
}
export default meta

type Story = StoryObj<typeof ScoutOwners>

export const States: Story = {
    render: () => (
        <div className="flex flex-col gap-3">
            {[
                ['One owner', scout('scout-checkout-health')],
                ['Several owners', scout('scout-enterprise-adoption')],
                ['Unowned', scout('scout-api-latency')],
                ['Canonical scout', scout('scout-error-tracking')],
            ].map(([label, config]) => (
                <div key={label as string} className="flex items-center gap-3">
                    <span className="w-36 text-xs text-muted">{label as string}</span>
                    <ScoutOwners config={config as SignalScoutConfigApi} />
                </div>
            ))}
        </div>
    ),
}
