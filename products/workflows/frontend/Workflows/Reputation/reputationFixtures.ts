import type { useMocks } from '~/mocks/jest'

import type {
    TeamEmailReputationResponseApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

/** A workflow row of the reputation response. A pause reason marks the workflow as paused. */
export function workflowRates(
    id: string,
    name: string,
    rates: Pick<WorkflowEmailSendingRatesApi, 'emails_sent' | 'bounce_rate' | 'complaint_rate'>,
    pausedReason?: string
): WorkflowEmailSendingRatesApi {
    return {
        hog_flow_id: id,
        hog_flow_name: name,
        ...rates,
        email_sending_paused: pausedReason !== undefined,
        email_sending_paused_at: pausedReason !== undefined ? '2026-09-01T00:00:00Z' : null,
        email_sending_paused_reason: pausedReason ?? '',
    }
}

// The newsletter causes the most bounces in absolute terms but only because it sends the most:
// its rate matches the project's. The import bounces far more than its volume predicts.
const NEWSLETTER = workflowRates('wf-newsletter', 'Newsletter', {
    emails_sent: 8000,
    bounce_rate: 0.02,
    complaint_rate: 0.0002,
})
const OLD_IMPORT = workflowRates('wf-import', 'Old list import', {
    emails_sent: 1500,
    bounce_rate: 0.06,
    complaint_rate: 0.0003,
})
const ONBOARDING = workflowRates('wf-onboarding', 'Onboarding', {
    emails_sent: 1000,
    bounce_rate: 0.035,
    complaint_rate: 0.0002,
})
const WIN_BACK = workflowRates(
    'wf-win-back',
    'Win-back',
    { emails_sent: 400, bounce_rate: 0.08, complaint_rate: 0.004 },
    'Paused because the hard bounce rate reached 8%.'
)

export const HEALTHY: TeamEmailReputationResponseApi = {
    aws: { health: 'healthy', sending_status: 'ENABLED', findings: [] },
    reputation: { bounce_rate: 0.004, complaint_rate: 0.0001, emails_sent: 20000 },
    workflows: [
        workflowRates('wf-digest', 'Digest', { emails_sent: 20000, bounce_rate: 0.004, complaint_rate: 0.0001 }),
    ],
    isps: [
        {
            isp: 'Gmail',
            emails_sent: 15000,
            delivery_rate: 0.99,
            bounce_rate: 0.003,
            transient_bounce_rate: 0.01,
            complaint_rate: null,
            complaint_base: 0,
            unavailable: [],
        },
    ],
    isp_shared_domains: [],
    isp_withheld_domains: [],
    email_sending_suspended: false,
    email_sending_suspended_at: null,
    email_sending_suspension_reason: '',
    sending_allowance: null,
}

export const NEEDS_WORK: TeamEmailReputationResponseApi = {
    ...HEALTHY,
    aws: {
        health: 'critical',
        sending_status: 'ENABLED',
        findings: [
            { finding_type: 'DMARC', impact: 'LOW', description: 'DMARC1', last_updated_at: null },
            { finding_type: 'BOUNCE', impact: 'HIGH', description: 'Bounce rate', last_updated_at: null },
        ],
    },
    reputation: { bounce_rate: 0.029, complaint_rate: 0.0003, emails_sent: 10900 },
    workflows: [WIN_BACK, OLD_IMPORT, ONBOARDING, NEWSLETTER],
    isps: [
        ...HEALTHY.isps,
        {
            isp: 'Yahoo',
            emails_sent: 2000,
            delivery_rate: 0.93,
            bounce_rate: 0.045,
            transient_bounce_rate: 0.02,
            complaint_rate: 0.0005,
            complaint_base: 1800,
            unavailable: [],
        },
        {
            // Too little volume to judge: one bounce here reads as 50%.
            isp: 'Aol',
            emails_sent: 2,
            delivery_rate: 0.5,
            bounce_rate: 0.5,
            transient_bounce_rate: 0,
            complaint_rate: 0,
            complaint_base: 1,
            unavailable: [],
        },
        {
            isp: 'Hotmail',
            emails_sent: 3000,
            delivery_rate: null,
            bounce_rate: null,
            transient_bounce_rate: null,
            complaint_rate: null,
            complaint_base: 0,
            unavailable: ['delivery', 'bounce', 'transient_bounce', 'complaint'],
        },
    ],
}

/** Serves a reputation response, narrowed by `search` the way the endpoint narrows it. */
export function reputationMocks(response: TeamEmailReputationResponseApi): Parameters<typeof useMocks>[0] {
    return {
        get: {
            '/api/projects/:team_id/hog_flows/reputation/': (req) => {
                const search = new URL(req.request.url).searchParams.get('search')?.toLowerCase()
                return [
                    200,
                    search
                        ? {
                              ...response,
                              workflows: response.workflows.filter((w) =>
                                  w.hog_flow_name.toLowerCase().includes(search)
                              ),
                          }
                        : response,
                ]
            },
        },
    }
}
