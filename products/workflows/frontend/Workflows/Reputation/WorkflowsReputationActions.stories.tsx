import { Meta, StoryFn } from '@storybook/react'
import { within } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowRates } from './reputationFixtures'
import { ReputationTab } from './ReputationTab'

const reputationEndpoint = '/api/projects/:team_id/hog_flows/reputation'

const healthyResponse: TeamEmailReputationResponseApi = {
    aws: { health: 'healthy', sending_status: 'ENABLED', findings: [] },
    reputation: { bounce_rate: 0.0062, complaint_rate: 0.0001, emails_sent: 115025 },
    workflows: [
        workflowRates('wf-1', 'Weekly digest', { emails_sent: 42000, bounce_rate: 0.006, complaint_rate: 0.0002 }),
        // Under the complaint floor: 0.56% here is one complaint in 180 sends, so the rate shows
        // without a verdict and does not become a fix.
        workflowRates('wf-2', 'Trial nudge', { emails_sent: 180, bounce_rate: 0.011, complaint_rate: 0.0056 }),
    ],
    isps: [
        {
            isp: 'Gmail',
            emails_sent: 84000,
            delivery_rate: 0.97,
            bounce_rate: 0.008,
            transient_bounce_rate: 0.02,
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

const fullResponse: TeamEmailReputationResponseApi = {
    ...healthyResponse,
    aws: {
        health: 'critical',
        sending_status: 'ENABLED',
        findings: [
            { finding_type: 'BOUNCE', impact: 'HIGH', description: 'Bounce rate', last_updated_at: null },
            { finding_type: 'DMARC', impact: 'LOW', description: 'DMARC1', last_updated_at: null },
        ],
    },
    reputation: { bounce_rate: 0.021, complaint_rate: 0.0006, emails_sent: 62000 },
    workflows: [
        workflowRates(
            'wf-3',
            'Win-back: inactive 90 days',
            { emails_sent: 3100, bounce_rate: 0.058, complaint_rate: 0.0034 },
            'Hard bounce rate reached 5.8% over the last 7 days, above the 5% limit.'
        ),
        // Sends the most and so bounces the most, but at the project's own rate.
        workflowRates('wf-1', 'Weekly digest', { emails_sent: 42000, bounce_rate: 0.015, complaint_rate: 0.0003 }),
        workflowRates('wf-4', 'Imported leads intro', {
            emails_sent: 6200,
            bounce_rate: 0.071,
            complaint_rate: 0.0009,
        }),
        workflowRates('wf-5', 'Abandoned setup reminder', {
            emails_sent: 5400,
            bounce_rate: 0.034,
            complaint_rate: 0.0004,
        }),
        workflowRates('wf-6', 'Product update', { emails_sent: 5300, bounce_rate: 0.012, complaint_rate: 0.0021 }),
    ],
    isps: [
        ...healthyResponse.isps,
        {
            isp: 'Yahoo',
            emails_sent: 6300,
            delivery_rate: 0.9,
            bounce_rate: 0.052,
            transient_bounce_rate: 0.03,
            complaint_rate: 0.0011,
            complaint_base: 900,
            unavailable: [],
        },
    ],
}

const partialResponse: TeamEmailReputationResponseApi = {
    ...healthyResponse,
    aws: null,
    isps: [],
    reputation: { bounce_rate: 0.011, complaint_rate: 0.0007, emails_sent: 12237 },
    workflows: [
        workflowRates('wf-7', 'Review request', { emails_sent: 1924, bounce_rate: 0.0078, complaint_rate: 0.0036 }),
        workflowRates('wf-8', 'Reactivation offer', { emails_sent: 2300, bounce_rate: 0.0383, complaint_rate: 0.0004 }),
        workflowRates('wf-9', 'Order shipped', { emails_sent: 2616, bounce_rate: 0.005, complaint_rate: 0.0004 }),
    ],
}

const noEmailResponse: TeamEmailReputationResponseApi = {
    ...healthyResponse,
    aws: null,
    reputation: null,
    workflows: [],
    isps: [],
    sending_allowance: { ...healthyResponse.sending_allowance!, emails_sent_last_hour: 0, emails_sent_last_day: 0 },
}

const meta: Meta<typeof ReputationTab> = {
    title: 'Products/Workflows/Reputation/Action list',
    component: ReputationTab,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: true },
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_ISP_SENDING_HEALTH, FEATURE_FLAGS.WORKFLOWS_REPUTATION_ACTION_LIST],
    },
}
export default meta

function mockReputation(response: TeamEmailReputationResponseApi): Record<string, any> {
    return { get: { [reputationEndpoint]: response } }
}

export const FullData: StoryFn = () => {
    useStorybookMocks(mockReputation(fullResponse))
    return <ReputationTab />
}

export const PartialData: StoryFn = () => {
    useStorybookMocks(mockReputation(partialResponse))
    return <ReputationTab />
}

export const NothingToFix: StoryFn = () => {
    useStorybookMocks(mockReputation(healthyResponse))
    return <ReputationTab />
}

export const NoEmail: StoryFn = () => {
    useStorybookMocks(mockReputation(noEmailResponse))
    return <ReputationTab />
}

export const SendingDisabled: StoryFn = () => {
    useStorybookMocks(
        mockReputation({
            ...fullResponse,
            aws: { ...fullResponse.aws!, health: 'suspended', sending_status: 'DISABLED' },
        })
    )
    return <ReputationTab />
}

export const LoadError: StoryFn = () => {
    useStorybookMocks({ get: { [reputationEndpoint]: [500, { detail: 'Server error' }] } })
    return <ReputationTab />
}

function openProviderTab(expected: string | RegExp): StoryFn['play'] {
    return async ({ canvasElement }) => {
        const tab = await within(canvasElement).findByText('By mailbox provider')
        tab.click()
        await within(canvasElement).findByText(expected)
    }
}

export const ProviderBreakdownOpen: StoryFn = () => {
    useStorybookMocks(mockReputation(fullResponse))
    return <ReputationTab />
}
ProviderBreakdownOpen.play = openProviderTab('Delivery rate')

export const ProviderBreakdownWithSharedDomain: StoryFn = () => {
    useStorybookMocks(mockReputation({ ...fullResponse, isp_shared_domains: ['mail.example.com'] }))
    return <ReputationTab />
}
ProviderBreakdownWithSharedDomain.play = openProviderTab('Delivery rate')

export const DomainWithheldFromCaller: StoryFn = () => {
    // A domain a project the viewer cannot open also sends from: excluded rather than blended in.
    useStorybookMocks(mockReputation({ ...fullResponse, isps: [], isp_withheld_domains: ['mail.example.com'] }))
    return <ReputationTab />
}
DomainWithheldFromCaller.play = openProviderTab(/left out of the provider breakdown/)

export const LongListCollapsed: StoryFn = () => {
    useStorybookMocks(
        mockReputation({
            ...fullResponse,
            workflows: [
                ...fullResponse.workflows,
                workflowRates('wf-7', 'Renewal reminder', {
                    emails_sent: 2400,
                    bounce_rate: 0.041,
                    complaint_rate: 0.0003,
                }),
                workflowRates('wf-8', 'Event invite', {
                    emails_sent: 1800,
                    bounce_rate: 0.009,
                    complaint_rate: 0.0016,
                }),
            ],
        })
    )
    return <ReputationTab />
}

// The scene width left by a 1280px window with the nav sidebar and the side panel open.
const NARROW_SCENE_CLASS = 'w-[520px]'

export const NarrowScene: StoryFn = () => {
    useStorybookMocks(mockReputation(fullResponse))
    return (
        <div className={NARROW_SCENE_CLASS}>
            <ReputationTab />
        </div>
    )
}

export const NarrowNothingToFix: StoryFn = () => {
    useStorybookMocks(mockReputation(healthyResponse))
    return (
        <div className={NARROW_SCENE_CLASS}>
            <ReputationTab />
        </div>
    )
}

export const FlagOff: StoryFn = () => {
    useStorybookMocks(mockReputation(fullResponse))
    return <ReputationTab />
}
FlagOff.parameters = { featureFlags: [FEATURE_FLAGS.WORKFLOWS_ISP_SENDING_HEALTH] }
