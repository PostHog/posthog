import type { Meta, StoryObj } from '@storybook/react'

import type { DeliveryPipelineApi } from '../generated/api.schemas'
import { DeliveryPipeline } from './DeliveryPipeline'

const FULL: DeliveryPipelineApi = {
    merged_pr_count: 52,
    stages: [
        { stage: 'open_to_gate', median_seconds: 16 * 3600 + 18 * 60, p90_seconds: 4 * 86400, pr_count: 39 },
        { stage: 'gate_to_merge', median_seconds: 30 * 60 + 42, p90_seconds: 3 * 3600 + 8 * 60, pr_count: 39 },
    ],
}

const meta: Meta<typeof DeliveryPipeline> = {
    title: 'Scenes-App/Engineering Analytics/Delivery Pipeline',
    component: DeliveryPipeline,
    parameters: {
        layout: 'fullscreen',
        testOptions: { snapshotBrowsers: ['chromium'], viewport: { width: 900, height: 320 } },
    },
    decorators: [
        (Story) => (
            <div className="p-6">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof DeliveryPipeline>

export const AllStages: Story = {
    args: { pipeline: FULL, mergeToDeploy: { medianSeconds: 29 * 60 + 42, prCount: 48 } },
}

// Without the deployments source the deploy leg is absent, not zero.
export const WithoutDeploys: Story = {
    args: { pipeline: FULL, mergeToDeploy: null },
}

export const NothingMerged: Story = {
    args: {
        pipeline: {
            merged_pr_count: 0,
            stages: FULL.stages.map((stage) => ({ ...stage, median_seconds: null, p90_seconds: null, pr_count: 0 })),
        },
        mergeToDeploy: null,
    },
}
