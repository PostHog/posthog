import { urls } from 'scenes/urls'

import type {
    AwsTenantFindingApi,
    IspSendingHealthApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { ReputationActionInputs, buildReputationActions } from './reputationActions'
import { REPUTATION_DOCS_URL } from './reputationUtils'

function workflow(
    id: string,
    rates: Pick<WorkflowEmailSendingRatesApi, 'emails_sent' | 'bounce_rate' | 'complaint_rate'>
): WorkflowEmailSendingRatesApi {
    return {
        hog_flow_id: id,
        hog_flow_name: id,
        ...rates,
        email_sending_paused: false,
        email_sending_paused_at: null,
        email_sending_paused_reason: '',
    }
}

function finding(finding_type: AwsTenantFindingApi['finding_type'], impact: 'LOW' | 'HIGH'): AwsTenantFindingApi {
    return { finding_type, impact, description: '', last_updated_at: null }
}

const YAHOO_BOUNCING: IspSendingHealthApi = {
    isp: 'Yahoo',
    emails_sent: 2000,
    delivery_rate: 0.9,
    bounce_rate: 0.06,
    transient_bounce_rate: 0.02,
    complaint_rate: 0.0002,
    complaint_base: 1800,
    unavailable: [],
}

const BASE: ReputationActionInputs = {
    aws: { health: 'healthy', sending_status: 'ENABLED', findings: [] },
    rates: { bounce_rate: 0.004, complaint_rate: 0.0001, emails_sent: 20000 },
    workflows: [workflow('digest', { emails_sent: 20000, bounce_rate: 0.004, complaint_rate: 0.0001 })],
    isps: [],
    sharedDomains: [],
    suspended: false,
    tabUrl: urls.workflows,
}

const MANY_SMALL = Array.from({ length: 10 }, (_, i) =>
    workflow(`small-${i}`, { emails_sent: 30, bounce_rate: 0.067, complaint_rate: 0.004 })
)

describe('buildReputationActions', () => {
    it.each<[string, Partial<ReputationActionInputs>, { key: string; severity: string }[]]>([
        [
            'flags a paused tenant even when the provider names no finding',
            {
                aws: { health: 'critical', sending_status: 'DISABLED', findings: [] },
                rates: { bounce_rate: 0.067, complaint_rate: 0.004, emails_sent: 300 },
                workflows: MANY_SMALL,
            },
            [
                { key: 'provider-status', severity: 'high' },
                { key: 'project-bounce', severity: 'high' },
            ],
        ],
        [
            'flags a warning verdict with no finding',
            { aws: { health: 'warning', sending_status: 'ENABLED', findings: [] } },
            [{ key: 'provider-status', severity: 'medium' }],
        ],
        ['flags a PostHog suspension', { suspended: true }, [{ key: 'project-suspended', severity: 'high' }]],
        [
            'ranks complaints over bounces and optional DNS work last',
            {
                aws: {
                    health: 'warning',
                    sending_status: 'ENABLED',
                    findings: [finding('BIMI', 'LOW'), finding('DMARC', 'LOW')],
                },
                rates: { bounce_rate: 0.1, complaint_rate: 0.002, emails_sent: 3000 },
                workflows: [
                    workflow('bouncy', { emails_sent: 1000, bounce_rate: 0.3, complaint_rate: 0 }),
                    workflow('spammy', { emails_sent: 2000, bounce_rate: 0, complaint_rate: 0.008 }),
                ],
            },
            [
                { key: 'workflow-complaint:spammy', severity: 'medium' },
                { key: 'workflow-bounce:bouncy', severity: 'medium' },
                { key: 'finding:DMARC', severity: 'medium' },
                { key: 'finding:BIMI', severity: 'low' },
            ],
        ],
    ])('%s', (_, overrides, expected) => {
        const actions = buildReputationActions({ ...BASE, ...overrides })

        expect(actions.map(({ key, severity }) => ({ key, severity }))).toEqual(expected)
    })

    it('points a bounce finding with no clear culprit at the guide, not at a tiny workflow', () => {
        const [bounceFinding] = buildReputationActions({
            ...BASE,
            aws: { health: 'critical', sending_status: 'ENABLED', findings: [finding('BOUNCE', 'HIGH')] },
            rates: { bounce_rate: 0.0801, complaint_rate: 0, emails_sent: 10001 },
            workflows: [
                workflow('big', { emails_sent: 10000, bounce_rate: 0.08, complaint_rate: 0 }),
                workflow('tiny', { emails_sent: 1, bounce_rate: 1, complaint_rate: 0 }),
            ],
        })

        expect(bounceFinding.primary.to).toEqual(REPUTATION_DOCS_URL)
    })

    it('keeps links on the surface the tab renders under', () => {
        const [complaintAction] = buildReputationActions({
            ...BASE,
            tabUrl: urls.broadcasts,
            workflows: [workflow('spammy', { emails_sent: 2000, bounce_rate: 0, complaint_rate: 0.008 })],
        })

        expect(complaintAction.secondary?.to).toEqual(urls.broadcasts('opt-outs'))
    })

    it('says when a provider row counts email from other projects', () => {
        const [providerAction] = buildReputationActions({
            ...BASE,
            isps: [YAHOO_BOUNCING],
            sharedDomains: ['mail.example.com'],
        })

        expect(providerAction.key).toEqual('provider-bounce:Yahoo')
        expect(providerAction.description).toContain('mail.example.com')
    })
})
