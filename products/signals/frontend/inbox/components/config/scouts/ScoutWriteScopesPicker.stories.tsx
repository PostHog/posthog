import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ScoutWriteScopesPicker } from './ScoutWriteScopesPicker'

/** Stories drive the picker like its call sites do: selection state lives outside. */
function ControlledPicker({
    compact,
    initialScopes = [],
    disabledReason,
}: {
    compact?: boolean
    initialScopes?: string[]
    disabledReason?: string
}): JSX.Element {
    const [selectedScopes, setSelectedScopes] = useState<string[]>(initialScopes)
    return (
        <ScoutWriteScopesPicker
            compact={compact}
            selectedScopes={selectedScopes}
            onChange={setSelectedScopes}
            disabledReason={disabledReason}
        />
    )
}

const meta: Meta<typeof ScoutWriteScopesPicker> = {
    title: 'Scenes-App/Inbox/ScoutWriteScopesPicker',
    component: ScoutWriteScopesPicker,
}
export default meta
type Story = StoryObj<typeof ScoutWriteScopesPicker>

export const ReadOnlyScout: Story = {
    render: () => (
        <div className="max-w-2xl p-4">
            <ControlledPicker />
        </div>
    ),
}

export const WithGrantedScopes: Story = {
    render: () => (
        <div className="max-w-2xl p-4">
            <ControlledPicker initialScopes={['dashboard:write', 'insight:write']} />
        </div>
    ),
}

export const ScoutSettingsVariant: Story = {
    render: () => (
        <div className="max-w-md p-4">
            <ControlledPicker compact initialScopes={['alert:write']} />
        </div>
    ),
}

export const CannotEdit: Story = {
    render: () => (
        <div className="max-w-md p-4">
            <ControlledPicker
                compact
                initialScopes={['dashboard:write']}
                disabledReason="Only this scout's owners (Ada Ellis) or a project admin can change its write access"
            />
        </div>
    ),
}
