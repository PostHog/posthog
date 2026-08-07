import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { ScoutModel, SignalTeamConfig } from '../../../types'
import { ScoutModelPicker } from './ScoutModelPicker'

// The picker reads the whole team config singleton, so a story is just that row's `scout_model`.
// Null is "Auto" — what a team that never touched the setting sees.
function ConfiguredPicker({
    scoutModel,
    className,
}: {
    scoutModel: ScoutModel | null
    /** The config column is narrower than the page, and the picker wraps — so width is the story. */
    className: string
}): JSX.Element {
    const config: SignalTeamConfig = { default_autostart_priority: 'P2', scout_model: scoutModel }
    useStorybookMocks({
        get: {
            '/api/projects/:id/signals/config/': config,
        },
    })
    return (
        <div className={`p-4 bg-surface-secondary ${className}`}>
            <ScoutModelPicker />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/ScoutModelPicker',
    component: ScoutModelPicker,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2026-06-11',
    },
}
export default meta

type Story = StoryObj

export const Auto: Story = {
    render: () => <ConfiguredPicker scoutModel={null} className="w-[720px]" />,
}

export const SpecificModel: Story = {
    render: () => <ConfiguredPicker scoutModel="claude-opus-5" className="w-[720px]" />,
}

// Config-column width, where the segmented control wraps below the copy.
export const Narrow: Story = {
    render: () => <ConfiguredPicker scoutModel={null} className="w-[420px]" />,
}
