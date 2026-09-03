import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { WorkflowsReputation } from './WorkflowsReputation'

const reputationEndpoint = '/api/projects/:team_id/hog_flows/reputation'

// A fortnight where Gmail starts filtering us halfway through while everyone else stays fine.
// This is the shape the project-wide rates hide, so it's what the stories are built around.
function gmailSeries(): TeamEmailReputationResponseApi['isps'][number]['daily'] {
    return Array.from({ length: 14 }, (_, day) => {
        const filtered = day >= 7
        return {
            date: `2026-08-${String(day + 1).padStart(2, '0')}`,
            emails_sent: 6000,
            delivery_rate: filtered ? 0.42 : 0.97,
            bounce_rate: 0.008,
        }
    })
}

function steadySeries(deliveryRate: number): TeamEmailReputationResponseApi['isps'][number]['daily'] {
    return Array.from({ length: 14 }, (_, day) => ({
        date: `2026-08-${String(day + 1).padStart(2, '0')}`,
        emails_sent: 900,
        delivery_rate: deliveryRate,
        bounce_rate: 0.004,
    }))
}

const baseResponse: TeamEmailReputationResponseApi = {
    aws: { health: 'healthy', sending_status: 'ENABLED', findings: [] },
    reputation: { bounce_rate: 0.0062, complaint_rate: 0.0001, emails_sent: 115025 },
    workflows: [],
    isps: [
        {
            isp: 'Gmail',
            emails_sent: 84000,
            delivery_rate: 0.69,
            bounce_rate: 0.008,
            // Gmail runs no feedback loop, so a complaint rate here would be unmeasurable.
            complaint_rate: null,
            unavailable: [],
            daily: gmailSeries(),
        },
        {
            isp: 'Outlook',
            emails_sent: 12600,
            delivery_rate: 0.98,
            bounce_rate: 0.004,
            complaint_rate: 0.0004,
            unavailable: [],
            daily: steadySeries(0.98),
        },
        {
            isp: 'Apple',
            emails_sent: 8100,
            // Steady, but steadily poor: the case an auto-scaled axis would draw as a flat line
            // indistinguishable from a healthy provider.
            delivery_rate: 0.45,
            bounce_rate: 0.012,
            complaint_rate: null,
            unavailable: [],
            daily: steadySeries(0.45),
        },
        {
            isp: 'Yahoo',
            emails_sent: 6300,
            delivery_rate: 0.96,
            bounce_rate: 0.006,
            complaint_rate: 0.0011,
            unavailable: [],
            daily: steadySeries(0.96),
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
