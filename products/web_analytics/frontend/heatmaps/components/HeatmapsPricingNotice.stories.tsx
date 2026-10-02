import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { HeatmapsPricingNotice } from './HeatmapsPricingNotice'

const captureSettingsMock = (urlAllowlist: string[]): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:id/heatmap_capture/settings/': {
                capture_mode: 'url_allowlist',
                url_allowlist: urlAllowlist,
                enforcement_enabled: false,
                can_capture_all_urls: false,
                capture_url_limit: 3,
            },
            '/api/projects/:id/heatmap_capture/pages/': { pages: [] },
        },
    })

const meta: Meta<typeof HeatmapsPricingNotice> = {
    title: 'Web Analytics/Heatmaps/Pricing notice',
    component: HeatmapsPricingNotice,
    decorators: [
        (Story) => (
            <div className="w-200">
                <Story />
            </div>
        ),
    ],
    parameters: {
        featureFlags: [FEATURE_FLAGS.HEATMAPS_PRICING_NOTICE],
        testOptions: {
            waitForSelector: '[data-attr="heatmaps-pricing-notice-review-urls"]',
        },
    },
}
export default meta
type Story = StoryObj<typeof HeatmapsPricingNotice>

export const WithCaptureList: Story = {
    decorators: [captureSettingsMock(['https://example.com/', 'https://example.com/pricing'])],
}

export const EmptyCaptureList: Story = {
    decorators: [captureSettingsMock([])],
}
