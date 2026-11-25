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
        tier: 1,
        max_tier: 7,
        emails_per_day: 1000,
        max_batch_audience: 1000,
        rate_limited_max_batch_audience: 3000,
        emails_sent_last_day: 640,
        enforced: true,
        next_tier: {
            emails_per_day: 3000,
            daily_target: 500,
            days_required: 2,
            days_reached: 1,
            not_before: '2026-09-02T07:15:00Z',
        },
        recent_rates: {
            window_days: 7,
            emails_sent: 2900,
            bounce_rate: 0.004,
            complaint_rate: 0.0002,
            max_bounce_rate: 0.02,
            max_complaint_rate: 0.001,
            complaints: 1,
            bounces_within_limits: true,
            complaints_within_limits: true,
        },
        recent_changes: [
            {
                changed_at: '2026-08-30T07:15:00Z',
                previous_emails_per_day: 100,
                emails_per_day: 1000,
                reason: 'clean_and_used',
            },
        ],
    },
    email_sending_suspended: false,
    email_sending_suspended_at: null,
    email_sending_suspension_reason: '',
    infrastructure: null,
}

const meta: Meta<typeof WorkflowsReputation> = {
    title: 'Products/Workflows/Reputation',
    component: WorkflowsReputation,
    parameters: {
        layout: 'padded',
        // Pinned before the Nov 3, 2026 email metrics incident so its banner stays out of the snapshots.
        mockDate: '2026-09-04 12:00:00',
        testOptions: { waitForLoadersToDisappear: true },
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_SENDING_TIER_REQUESTS],
    },
    decorators: [
        // The scene root is a size container, so it adds no width of its own. The padded layout
        // shrink-wraps the story root in visual review, which would collapse the scene to zero width.
        // A fixed width also lets a story set the scene width that the container queries respond to.
        (Story, { parameters }) => (
            <div className={parameters.sceneWidth === 'narrow' ? 'w-130' : 'w-300'}>
                <Story />
            </div>
        ),
    ],
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

export const HighBounceRate: StoryFn = () => {
    useStorybookMocks(
        mockReputation({
            ...baseResponse,
            reputation: { bounce_rate: 0.072, complaint_rate: 0.0001, emails_sent: 115025 },
        })
    )
    return <WorkflowsReputation />
}
HighBounceRate.parameters = { testOptions: { snapshotBrowsers: [] } }

const withInfrastructure: TeamEmailReputationResponseApi = {
    ...baseResponse,
    infrastructure: {
        emails_sent_at_least: 4_000_000,
        delivery_rate: 0.991,
        bounce_rate: 0.0028,
        complaint_rate: 0.0003,
    },
}

export const WithInfrastructureHealth: StoryFn = () => {
    useStorybookMocks(mockReputation(withInfrastructure))
    return <WorkflowsReputation />
}

export const WithInfrastructureHealthInNarrowScene: StoryFn = () => {
    useStorybookMocks(mockReputation(withInfrastructure))
    return <WorkflowsReputation />
}
// A 1280px window with the nav and the side panel open leaves about 520px of scene. The cards and the
// allowance columns must stack by the scene's width, which a wide story viewport alone never shows.
WithInfrastructureHealthInNarrowScene.parameters = { sceneWidth: 'narrow' }

export const AllowanceWaitingAfterChange: StoryFn = () => {
    // Raised recently, so the time-at-tier wait still applies whatever the project sends.
    useStorybookMocks(
        mockReputation({
            ...baseResponse,
            sending_allowance: {
                ...baseResponse.sending_allowance!,
                tier: 3,
                emails_per_day: 10000,
                max_batch_audience: 10000,
                rate_limited_max_batch_audience: null,
                emails_sent_last_day: 0,
                next_tier: {
                    emails_per_day: 30000,
                    daily_target: 5000,
                    days_required: 2,
                    days_reached: 0,
                    not_before: '2026-09-08T07:15:00Z',
                },
            },
        })
    )
    return <WorkflowsReputation />
}

export const AllowanceAtTopTier: StoryFn = () => {
    useStorybookMocks(
        mockReputation({
            ...baseResponse,
            sending_allowance: {
                ...baseResponse.sending_allowance!,
                tier: 7,
                emails_per_day: 1000000,
                max_batch_audience: 1000000,
                rate_limited_max_batch_audience: null,
                emails_sent_last_day: 212000,
                next_tier: null,
                recent_changes: [],
            },
        })
    )
    return <WorkflowsReputation />
}
AllowanceAtTopTier.parameters = { testOptions: { snapshotBrowsers: [] } }

export const AllowanceRatesOverLimit: StoryFn = () => {
    // The 30-day rates further down still read healthy while the 7-day bounce rate is over.
    useStorybookMocks(
        mockReputation({
            ...baseResponse,
            sending_allowance: {
                ...baseResponse.sending_allowance!,
                tier: 2,
                emails_per_day: 3000,
                max_batch_audience: 3000,
                rate_limited_max_batch_audience: null,
                emails_sent_last_day: 1200,
                next_tier: {
                    ...baseResponse.sending_allowance!.next_tier!,
                    emails_per_day: 10000,
                    daily_target: 1500,
                    days_reached: 0,
                },
                recent_rates: {
                    ...baseResponse.sending_allowance!.recent_rates!,
                    emails_sent: 6400,
                    bounce_rate: 0.031,
                    bounces_within_limits: false,
                },
                recent_changes: [
                    {
                        changed_at: '2026-09-01T07:15:00Z',
                        previous_emails_per_day: 10000,
                        emails_per_day: 3000,
                        reason: 'rates_above_threshold',
                    },
                    {
                        changed_at: '2026-08-20T07:15:00Z',
                        previous_emails_per_day: 1000,
                        emails_per_day: 10000,
                        reason: 'trusted_account',
                    },
                ],
            },
        })
    )
    return <WorkflowsReputation />
}
