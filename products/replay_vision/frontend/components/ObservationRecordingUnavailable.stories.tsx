import type { Meta, StoryObj } from '@storybook/react'

import { ObservationRecordingUnavailable } from './ObservationRecordingUnavailable'

const meta: Meta<typeof ObservationRecordingUnavailable> = {
    title: 'Replay Vision/Observation recording unavailable',
    component: ObservationRecordingUnavailable,
    args: {
        observationId: '0193f1c0-0000-0000-0000-000000000001',
        scannerId: '0193f1c0-0000-0000-0000-000000000002',
        sessionId: '0193f1c0-0000-0000-0000-000000000003',
        distinctId: 'person@example.com',
        analysisAvailable: true,
    },
}
export default meta

type Story = StoryObj<typeof ObservationRecordingUnavailable>

export const WithPerson: Story = {}

export const WithoutPerson: Story = { args: { distinctId: null } }

// Ineligible, failed, and in-progress observations have no scan result, so the copy must not claim one.
export const WithoutAnalysis: Story = { args: { analysisAvailable: false } }
