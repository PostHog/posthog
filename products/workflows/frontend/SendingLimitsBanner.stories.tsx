import { Meta, StoryFn } from '@storybook/react'

import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'

import type { WorkflowSendingLimitsApi } from 'products/workflows/frontend/generated/api.schemas'

import { SendingLimitsBanner } from './SendingLimitsBanner'

const sendingLimitsEndpoint = '/api/projects/:team_id/hog_flows/sending_limits/'

const meta: Meta = {
    title: 'Products/Workflows/SendingLimitsBanner',
    component: SendingLimitsBanner,
    parameters: {
        layout: 'padded',
        testOptions: { waitForSelector: '.LemonBanner' },
    },
}
export default meta

interface StoryProps {
    limits: WorkflowSendingLimitsApi
}

const Template: StoryFn<StoryProps> = ({ limits }) => {
    useStorybookMocks({ get: { [sendingLimitsEndpoint]: limits } })
    return <SendingLimitsBanner sendingAllowanceUrl={urls.workflows('reputation')} />
}

export const QuotaLimited: StoryFn<StoryProps> = Template.bind({})
QuotaLimited.args = {
    limits: {
        email_quota_limited: true,
        destination_quota_limited: true,
        email_daily_cap_reached: false,
        emails_per_day: null,
    },
}

export const DailyEmailCapReached: StoryFn<StoryProps> = Template.bind({})
DailyEmailCapReached.args = {
    limits: {
        email_quota_limited: false,
        destination_quota_limited: false,
        email_daily_cap_reached: true,
        emails_per_day: 1000,
    },
}
