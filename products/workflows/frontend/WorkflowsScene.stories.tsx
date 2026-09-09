import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { EmailSendingSuspensionStatusApi } from 'products/workflows/frontend/generated/api.schemas'

const workflow = {
    id: '019d307e-e615-0000-ac5a-b8ef4439370e',
    name: 'Welcome email',
    description: '',
    version: 1,
    status: 'active',
    created_at: '2026-08-01T09:00:00Z',
    updated_at: '2026-09-01T09:00:00Z',
    trigger: { type: 'event' },
    edges: [],
    actions: [],
    billable_action_types: ['function_email'],
}

function status(allowance: EmailSendingSuspensionStatusApi['sending_allowance']): EmailSendingSuspensionStatusApi {
    return {
        email_sending_suspended: false,
        email_sending_suspended_at: null,
        email_sending_suspension_reason: '',
        sending_allowance: allowance,
    }
}

const tierZero = {
    tier: 0,
    max_tier: 4,
    emails_per_hour: 10,
    emails_per_day: 100,
    max_batch_audience: 100,
    emails_sent_last_hour: 4,
    emails_sent_last_day: 12,
    enforced: true,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Workflows',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-09',
        pageUrl: urls.workflows(),
        testOptions: { waitForSelector: '[data-attr="workflows-scene-tabs"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/hog_flows/': { count: 1, results: [workflow] },
                '/api/projects/:team_id/hog_flows/': { count: 1, results: [workflow] },
                '/api/environments/:team_id/hog_flow_templates/': { count: 0, results: [] },
                '/api/environments/:team_id/messaging_categories/': { count: 0, results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const NoSendingLimitReached: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/hog_flows/email_sending_suspension': status(tierZero) },
        }),
    ],
}

export const DailySendingLimitReached: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/email_sending_suspension': status({
                    ...tierZero,
                    emails_sent_last_hour: 10,
                    emails_sent_last_day: 100,
                }),
            },
        }),
    ],
    parameters: { testOptions: { waitForSelector: '[data-attr="workflows-email-cap-banner"]' } },
}

export const HourlySendingLimitReached: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/email_sending_suspension': status({
                    ...tierZero,
                    emails_sent_last_hour: 10,
                    emails_sent_last_day: 46,
                }),
            },
        }),
    ],
    parameters: { testOptions: { waitForSelector: '[data-attr="workflows-email-cap-banner"]' } },
}
