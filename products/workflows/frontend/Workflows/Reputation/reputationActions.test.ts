import { urls } from 'scenes/urls'

import type {
    AwsTenantFindingApi,
    IspSendingHealthApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { ReputationAction, ReputationActionInputs, buildReputationActions } from './reputationActions'
import { workflowRates } from './reputationFixtures'
import { CHANNEL_SETUP_DOCS_URL, LOWER_RATES_DOCS_URL } from './reputationUtils'

function workflow(
    id: string,
    rates: Pick<WorkflowEmailSendingRatesApi, 'emails_sent' | 'bounce_rate' | 'complaint_rate'>
): WorkflowEmailSendingRatesApi {
    return workflowRates(id, id, rates)
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

    function targets(action: ReputationAction | undefined): { button?: string; docs?: string } | undefined {
        if (!action) {
            return undefined
        }
        const cta = action.cta
        const button =
            cta &&
            ('supportMessage' in cta ? 'support form' : 'breakdownTab' in cta ? `${cta.breakdownTab} tab` : cta.to)
        return { button, docs: action.docsLink?.to }
    }
    const openWorkflow = (id: string): string => `${urls.workflow(id, 'workflow')}?node=trigger_node`
    const optOuts = urls.workflows('opt-outs')
    const BOUNCY = workflow('bouncy', { emails_sent: 1000, bounce_rate: 0.3, complaint_rate: 0 })
    const SPAMMY = workflow('spammy', { emails_sent: 2000, bounce_rate: 0, complaint_rate: 0.008 })
    const QUIET = workflow('quiet', { emails_sent: 8000, bounce_rate: 0.004, complaint_rate: 0.0002 })
    const IMPORT = workflow('import', { emails_sent: 1500, bounce_rate: 0.06, complaint_rate: 0 })
    const flagged = (...findings: AwsTenantFindingApi[]): Partial<ReputationActionInputs> => ({
        aws: { health: 'warning', sending_status: 'ENABLED', findings },
    })

    it.each<[string, Partial<ReputationActionInputs>, { button?: string; docs?: string }]>([
        ['project-suspended', { suspended: true }, { button: 'support form' }],
        [
            'provider-status',
            { aws: { health: 'critical', sending_status: 'DISABLED', findings: [] } },
            { button: 'support form', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'provider-status',
            { aws: { health: 'warning', sending_status: 'ENABLED', findings: [] } },
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'paused:win-back',
            {
                workflows: [
                    workflowRates(
                        'win-back',
                        'Win-back',
                        { emails_sent: 400, bounce_rate: 0.08, complaint_rate: 0 },
                        'Paused.'
                    ),
                ],
            },
            { button: openWorkflow('win-back'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'finding:BOUNCE',
            {
                ...flagged(finding('BOUNCE', 'HIGH')),
                rates: { bounce_rate: 0.0263, complaint_rate: 0, emails_sent: 9500 },
                workflows: [QUIET, IMPORT],
            },
            { button: openWorkflow('import'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            // The only workflow above the project rate sent once, so it is too small to blame.
            'finding:BOUNCE',
            {
                ...flagged(finding('BOUNCE', 'HIGH')),
                rates: { bounce_rate: 0.0801, complaint_rate: 0, emails_sent: 10001 },
                workflows: [
                    workflow('big', { emails_sent: 10000, bounce_rate: 0.08, complaint_rate: 0 }),
                    workflow('tiny', { emails_sent: 1, bounce_rate: 1, complaint_rate: 0 }),
                ],
            },
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'finding:COMPLAINT',
            {
                ...flagged(finding('COMPLAINT', 'HIGH')),
                rates: { bounce_rate: 0.003, complaint_rate: 0.00176, emails_sent: 10000 },
                workflows: [QUIET, SPAMMY],
            },
            { button: openWorkflow('spammy'), docs: LOWER_RATES_DOCS_URL },
        ],
        ['finding:COMPLAINT', flagged(finding('COMPLAINT', 'HIGH')), { button: optOuts, docs: LOWER_RATES_DOCS_URL }],
        [
            'finding:DKIM',
            flagged(finding('DKIM', 'HIGH')),
            { button: urls.workflows('channels'), docs: CHANNEL_SETUP_DOCS_URL },
        ],
        ['finding:BIMI', flagged(finding('BIMI', 'LOW')), {}],
        [
            'finding:IP_LISTING',
            flagged(finding('IP_LISTING', 'HIGH')),
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'project-bounce',
            { rates: { bounce_rate: 0.067, complaint_rate: 0, emails_sent: 300 }, workflows: MANY_SMALL },
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'project-complaint',
            { rates: { bounce_rate: 0.004, complaint_rate: 0.004, emails_sent: 3000 }, workflows: MANY_SMALL },
            { button: optOuts, docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'workflow-bounce:bouncy',
            { workflows: [BOUNCY] },
            { button: openWorkflow('bouncy'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'workflow-complaint:spammy',
            { workflows: [SPAMMY] },
            { button: openWorkflow('spammy'), docs: LOWER_RATES_DOCS_URL },
        ],
        ['provider-bounce:Yahoo', { isps: [YAHOO_BOUNCING] }, { button: 'providers tab', docs: LOWER_RATES_DOCS_URL }],
    ])('gives %s the expected button and docs (case %#)', (key, overrides, expected) => {
        const action = buildReputationActions({ ...BASE, ...overrides }).find((item) => item.key === key)

        expect(targets(action)).toEqual(expected)
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
