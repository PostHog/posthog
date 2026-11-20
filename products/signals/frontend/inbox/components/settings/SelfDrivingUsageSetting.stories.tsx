import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'

import { expect } from 'storybook/test'

import { SelfDrivingUsageSetting } from './SelfDrivingUsageSetting'

const meta: Meta<typeof SelfDrivingUsageSetting> = {
    title: 'Scenes-App/Inbox/Self-driving usage setting',
    component: SelfDrivingUsageSetting,
    parameters: {
        viewMode: 'story',
        mockDate: '2026-06-11',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof SelfDrivingUsageSetting>

export const WithSpendBilling: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.SELF_DRIVING_QUOTA_ENFORCEMENT]: true } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/trial/': { enabled: false, grant_status: 'not_claimed' },
                '/api/projects/:team_id/signals/reports/refund-summary/': {
                    credited_refund_count: 0,
                    credited_credits: 0,
                    period_billable_credits: 0,
                    quota_limited: true,
                },
                '/api/billing': () => [
                    200,
                    {
                        ...billingJson,
                        products: [
                            {
                                ...billingJson.products[0],
                                type: 'inbox_usage',
                                name: 'Inbox usage',
                                usage_key: 'signals_spend_credits',
                                current_amount_usd: '12.34',
                                current_usage: 1234,
                            },
                        ],
                        usage_summary: { signals_spend_credits: { billing_start_date: '2020-01-01' } },
                    },
                ],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('1,234 credits')).toBeVisible()
        await expect(await canvas.findByText('Spending limit reached')).toBeVisible()
        await expect(canvas.getByText(/Work already underway will finish/)).toBeVisible()
    },
}
