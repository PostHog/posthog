import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ScoutRunSettingsToggles } from './ScoutRunSettingsToggles'

function ControlledToggles({
    initialEnabled = true,
    initialEmit = true,
    disabledReason,
}: {
    initialEnabled?: boolean
    initialEmit?: boolean
    disabledReason?: string
}): JSX.Element {
    const [enabled, setEnabled] = useState(initialEnabled)
    const [emit, setEmit] = useState(initialEmit)

    return (
        <ScoutRunSettingsToggles
            enabled={enabled}
            emit={emit}
            onEnabledChange={setEnabled}
            onEmitChange={setEmit}
            disabledReason={disabledReason}
        />
    )
}

const meta: Meta<typeof ScoutRunSettingsToggles> = {
    title: 'Scenes-App/Inbox/ScoutRunSettingsToggles',
    component: ScoutRunSettingsToggles,
    parameters: {
        featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY],
    },
}
export default meta
type Story = StoryObj<typeof ScoutRunSettingsToggles>

export const Default: Story = {
    render: () => <ControlledToggles />,
}

export const DryRun: Story = {
    render: () => <ControlledToggles initialEmit={false} />,
}

export const Disabled: Story = {
    render: () => <ControlledToggles disabledReason="Scout settings are unavailable" />,
}
