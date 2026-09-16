import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { WorkflowsReputation } from './WorkflowsReputation'

const reputationEndpoint = '/api/projects/:team_id/hog_flows/reputation'

const baseResponse: TeamEmailReputationResponseApi = {
    aws: { health: 'healthy', sending_status: 'ENABLED', findings: [] },
    reputation: { bounce_rate: 0.0062, complaint_rate: 0.0001, emails_sent: 115025 },
    workflows: [
        {
            hog_flow_id: '0199c0de-0000-7000-8000-000000000001',
            hog_flow_name: 'Weekly digest',
            emails_sent: 42000,
            bounce_rate: 0.006,
            complaint_rate: 0.0012,
            email_sending_paused: false,
            email_sending_paused_at: null,
            email_sending_paused_reason: '',
        },
        {
            // Under the complaint floor: 0.56% here is one complaint in 180 sends, so the rate
            // shows without a verdict. The bounce rate clears its own, much lower, floor.
            hog_flow_id: '0199c0de-0000-7000-8000-000000000002',
            hog_flow_name: 'Trial nudge',
            emails_sent: 180,
            bounce_rate: 0.011,
            complaint_rate: 0.0056,
            email_sending_paused: false,
            email_sending_paused_at: null,
            email_sending_paused_reason: '',
        },
    ],
    isps: [
        {
            isp: 'Gmail',
            emails_sent: 84000,
            delivery_rate: 0.69,
            bounce_rate: 0.008,
            transient_bounce_rate: 0.29,
            // Gmail runs no feedback loop, so a complaint rate here would be unmeasurable.
            complaint_rate: null,
            complaint_base: 0,
            unavailable: [],
        },
        {
            isp: 'ExchangeOnline',
            emails_sent: 12600,
            delivery_rate: 0.98,
            bounce_rate: 0.004,
            transient_bounce_rate: 0.012,
            complaint_rate: 0.0004,
            complaint_base: 11800,
            unavailable: [],
        },
        {
            isp: 'Icloud',
            emails_sent: 8100,
            delivery_rate: 0.45,
            bounce_rate: 0.012,
            transient_bounce_rate: 0.53,
            complaint_rate: null,
            complaint_base: 0,
            unavailable: [],
        },
        {
            isp: 'Yahoo',
            emails_sent: 6300,
            delivery_rate: 0.96,
            bounce_rate: 0.006,
            transient_bounce_rate: 0.03,
            complaint_rate: 0.0011,
            complaint_base: 900,
            unavailable: [],
        },
        {
            // Too little volume to rate: one bounce here would read as 12.5%.
            isp: 'Aol',
            emails_sent: 8,
            delivery_rate: 1,
            bounce_rate: 0,
            transient_bounce_rate: 0,
            complaint_rate: 0,
            complaint_base: 8,
            unavailable: [],
        },
    ],
    isp_shared_domains: [],
    isp_withheld_domains: [],
    sending_allowance: {
        tier: 2,
        max_tier: 4,
        emails_per_hour: 5000,
        emails_per_day: 50000,
        max_batch_audience: 25000,
        emails_sent_last_hour: 1200,
        emails_sent_last_day: 18400,
        enforced: true,
    },
    email_sending_suspended: false,
    email_sending_suspended_at: null,
    email_sending_suspension_reason: '',
}

const meta: Meta<typeof WorkflowsReputation> = {
    title: 'Products/Workflows/Reputation',
    component: WorkflowsReputation,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: true },
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_ISP_SENDING_HEALTH],
    },
}
export default meta

function mockReputation(response: TeamEmailReputationResponseApi): Record<string, any> {
    return { get: { [reputationEndpoint]: response } }
}

export const OneProviderFiltering: StoryFn = () => {
    useStorybookMocks(mockReputation(baseResponse))
    return <WorkflowsReputation />
}

export const SendingAllowanceNotYetApplied: StoryFn = () => {
    // Mid-rollout the allowance is measured but not applied. The card has to stay on screen and say
    // so, because a project whose batch was just capped still needs to read its audience limit.
    useStorybookMocks(
        mockReputation({
            ...baseResponse,
            sending_allowance: { ...baseResponse.sending_allowance!, enforced: false },
        })
    )
    return <WorkflowsReputation />
}

export const NoProviderData: StoryFn = () => {
    // What every project sees until Virtual Deliverability Manager is collecting.
    useStorybookMocks(mockReputation({ ...baseResponse, isps: [] }))
    return <WorkflowsReputation />
}

export const ProviderDataWithoutWorkflowRates: StoryFn = () => {
    // Domain-level sends with nothing from a workflow in the window: the card has to stay on screen
    // and say what the table below counts, rather than claiming there is no data.
    useStorybookMocks(mockReputation({ ...baseResponse, reputation: null, aws: null }))
    return <WorkflowsReputation />
}

export const SharedSendingDomain: StoryFn = () => {
    useStorybookMocks(mockReputation({ ...baseResponse, isp_shared_domains: ['mail.example.com'] }))
    return <WorkflowsReputation />
}

export const DomainWithheldFromCaller: StoryFn = () => {
    // A domain a project the viewer cannot open also sends from: excluded rather than blended in.
    useStorybookMocks(mockReputation({ ...baseResponse, isps: [], isp_withheld_domains: ['mail.example.com'] }))
    return <WorkflowsReputation />
}
