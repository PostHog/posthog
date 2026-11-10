import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { SelfDrivingTrialStatusApi } from '../../../generated/api.schemas'
import { SelfDrivingTrialUsage } from './SelfDrivingTrialUsage'

const activeTrial: SelfDrivingTrialStatusApi = {
    enabled: true,
    flag_confirmed: true,
    policy_version: 1,
    legacy_pr_restricted: false,
    billing_ready: true,
    eligible: false,
    can_activate: true,
    organization_grants_remaining: 1,
    grant_id: '00000000-0000-0000-0000-000000000001',
    grant_status: 'active',
    exhaustion_reason: '',
    reports_delivered: 2,
    reports_in_progress: 1,
    report_limit: 5,
    allowance_microusd: 10_000_000,
    used_microusd: 3_200_000,
    new_work_paused: false,
    enabled_scouts: 3,
    scout_limit: 3,
    scouts_to_pause: 0,
    paid_continuation: 'add_payment_method',
}

const meta: Meta<typeof SelfDrivingTrialUsage> = {
    title: 'Scenes-App/Inbox/TrialUsage',
    component: SelfDrivingTrialUsage,
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/signals/trial/': activeTrial } })],
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.SELF_DRIVING_UBP],
        mockDate: '2026-11-06',
        testOptions: { snapshotBrowsers: [], waitForSelector: '[aria-label="Self-driving free trial"]' },
    },
}
export default meta

type Story = StoryObj<typeof SelfDrivingTrialUsage>

export const Active: Story = {
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('Trial allowance used: 320 credits of 1,000 credits.')
    },
}

export const ReportLimitWithWorkInProgress: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/trial/': {
                    ...activeTrial,
                    grant_status: 'exhausted',
                    exhaustion_reason: 'report_limit',
                    reports_in_progress: 3,
                    new_work_paused: true,
                },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText(
            'The trial report limit has been reached, including reports still in progress.'
        )
        await within(canvasElement).findByRole('link', { name: 'Add payment method' })
    },
}

export const Exhausted: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/trial/': {
                    ...activeTrial,
                    grant_status: 'exhausted',
                    exhaustion_reason: 'cost_limit',
                    new_work_paused: true,
                    used_microusd: 10_000_000,
                },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByRole('link', { name: 'Add payment method' })
        await within(canvasElement).findByText(/Work already underway can finish at no additional charge/)
    },
}
