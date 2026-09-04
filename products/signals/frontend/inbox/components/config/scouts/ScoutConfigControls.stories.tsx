import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { mockScoutConfigs } from '../../../__mocks__/scoutConfigs'
import { ScoutConfigForm } from './ScoutConfigControls'

// The settings form a scout's gear opens. Use this to check that every row reads as the same kind of
// row, and that the mode, schedule, and network controls line up down the right edge.

function EditableConfigForm({ initialConfig }: { initialConfig: SignalScoutConfig }): JSX.Element {
    const [config, setConfig] = useState(initialConfig)

    return (
        <div className="w-[520px] p-2">
            <ScoutConfigForm
                config={config}
                onUpdate={(_, updates) => setConfig((current) => ({ ...current, ...updates }))}
            />
        </div>
    )
}

const meta: Meta<typeof ScoutConfigForm> = {
    title: 'Scenes-App/Inbox/ScoutConfigForm',
    component: ScoutConfigForm,
    parameters: {
        featureFlags: { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true, [FEATURE_FLAGS.SCOUTS_MODEL_CONFIG]: true },
    },
}
export default meta

type Story = StoryObj<typeof ScoutConfigForm>

export const Live: Story = {
    render: () => <EditableConfigForm initialConfig={mockScoutConfigs[0]} />,
}

// Dry run: the scout still runs on its schedule, its findings just never reach the inbox.
export const DryRun: Story = {
    render: () => <EditableConfigForm initialConfig={{ ...mockScoutConfigs[0], emit: false }} />,
}

// A scout that is switched off. Everything the next run would use stays editable; only the controls
// that would change that run's timing lock.
export const Disabled: Story = {
    render: () => <EditableConfigForm initialConfig={{ ...mockScoutConfigs[0], enabled: false }} />,
}

// A weekly schedule: the day picker and the time picker together write a `30 8 * * 4`-style cron.
export const WeeklySchedule: Story = {
    render: () => <EditableConfigForm initialConfig={{ ...mockScoutConfigs[0], run_cron_schedule: '30 8 * * 4' }} />,
}

// A schedule the presets cannot express. The expression is editable, and validated as it is typed.
export const CustomCronSchedule: Story = {
    render: () => <EditableConfigForm initialConfig={{ ...mockScoutConfigs[0], run_cron_schedule: '0 9 * * 1-5' }} />,
}
