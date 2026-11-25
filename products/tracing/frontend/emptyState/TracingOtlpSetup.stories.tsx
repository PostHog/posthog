import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { TracingOtlpSetup } from './TracingOtlpSetup'
import { tracingOtlpSetupLogic } from './tracingOtlpSetupLogic'

const meta: Meta<typeof TracingOtlpSetup> = {
    title: 'Scenes-App/Tracing/TracingOtlpSetup',
    component: TracingOtlpSetup,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof TracingOtlpSetup>

export const CollectorWithEnvironment: Story = {
    render: function Render() {
        const logic = useMountedLogic(tracingOtlpSetupLogic)
        // Set the state synchronously before the first paint, so the snapshot never sees the default tab.
        useState(() => {
            logic.actions.setPlatform('collector')
            logic.actions.setEnvironment('production')
            return null
        })
        return (
            <div className="max-w-[36rem]">
                <TracingOtlpSetup />
            </div>
        )
    },
}
