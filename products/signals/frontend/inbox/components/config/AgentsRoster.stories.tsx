import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { SignalSourceProduct, SignalSourceType } from '../../types'
import { AgentsRoster } from './AgentsRoster'

// The roster reads every source's config off one list endpoint, so a story is that list plus the
// dormancy verdict the roster fetches for itself.
const BASE_DATE = '2026-06-10T12:00:00Z'

function sourceConfig(sourceProduct: SignalSourceProduct, sourceType: SignalSourceType): Record<string, unknown> {
    return {
        id: `${sourceProduct}-${sourceType}`,
        source_product: sourceProduct,
        source_type: sourceType,
        enabled: true,
        config: {},
        status: null,
        created_at: BASE_DATE,
        updated_at: BASE_DATE,
    }
}

// Error tracking only counts as armed once all three of its signal types are on.
const ENABLED_SOURCE_CONFIGS = [
    sourceConfig(SignalSourceProduct.ErrorTracking, SignalSourceType.IssueCreated),
    sourceConfig(SignalSourceProduct.ErrorTracking, SignalSourceType.IssueReopened),
    sourceConfig(SignalSourceProduct.ErrorTracking, SignalSourceType.IssueSpiking),
    sourceConfig(SignalSourceProduct.Conversations, SignalSourceType.Ticket),
    sourceConfig(SignalSourceProduct.SessionReplay, SignalSourceType.SessionAnalysisCluster),
    sourceConfig(SignalSourceProduct.HealthChecks, SignalSourceType.HealthIssue),
]

function rosterStory(dormantSourceProducts: SignalSourceProduct[]): Story {
    return {
        parameters: { featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY] },
        decorators: [
            mswDecorator({
                get: {
                    '/api/projects/:id/signals/source_configs': () => [
                        200,
                        { results: ENABLED_SOURCE_CONFIGS, count: ENABLED_SOURCE_CONFIGS.length },
                    ],
                    '/api/projects/:id/signals/source_configs/dormancy': () => [
                        200,
                        { dormant_source_products: dormantSourceProducts, lookback_days: 30 },
                    ],
                },
            }),
        ],
        render: () => (
            <div className="p-4 bg-primary min-h-screen">
                <AgentsRoster />
            </div>
        ),
    }
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/AgentsRoster',
    component: AgentsRoster,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj

export const Default: Story = rosterStory([])

// Support is on and correctly wired, but nothing has come through the product in the lookback
// window, so it can never fire. The badge sits alongside sources that are genuinely working.
export const SupportDormant: Story = rosterStory([SignalSourceProduct.Conversations])
