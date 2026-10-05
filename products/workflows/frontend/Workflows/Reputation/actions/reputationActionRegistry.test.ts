import { readdirSync } from 'fs'
import { join } from 'path'

import { urls } from 'scenes/urls'

import {
    type AwsTenantFindingApi,
    FindingTypeEnumApi,
    type IspSendingHealthApi,
    type TeamEmailReputationResponseApi,
    type WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { HEALTHY, workflowRates } from '../reputationFixtures'
import { CHANNEL_SETUP_DOCS_URL, LOWER_RATES_DOCS_URL } from '../reputationUtils'
import type { RegisteredReputationAction } from './defineReputationAction'
import { buildReputationActionContext } from './reputationActionContext'
import { REPUTATION_ACTIONS, buildReputationActions } from './reputationActionRegistry'
import type { ReputationAction, ReputationPageControls } from './reputationActionTypes'

type Overrides = Partial<TeamEmailReputationResponseApi>

function workflow(
    id: string,
    rates: Pick<WorkflowEmailSendingRatesApi, 'emails_sent' | 'bounce_rate' | 'complaint_rate'>,
    pausedReason?: string
): WorkflowEmailSendingRatesApi {
    return workflowRates(id, id, rates, pausedReason)
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

const BASE: TeamEmailReputationResponseApi = {
    ...HEALTHY,
    workflows: [workflow('digest', { emails_sent: 20000, bounce_rate: 0.004, complaint_rate: 0.0001 })],
    isps: [],
}

const MANY_SMALL = Array.from({ length: 10 }, (_, i) =>
    workflow(`small-${i}`, { emails_sent: 30, bounce_rate: 0.067, complaint_rate: 0.004 })
)

function build(overrides: Overrides): ReputationAction[] {
    return buildReputationActions(
        buildReputationActionContext({ response: { ...BASE, ...overrides }, tabUrl: urls.workflows })
    )
}

const flagged = (...findings: AwsTenantFindingApi[]): Overrides => ({
    aws: { health: 'warning', sending_status: 'ENABLED', findings },
})

describe('buildReputationActions', () => {
    it.each<[string, Overrides, { key: string; severity: string; blocksSending: boolean }[]]>([
        [
            'flags a paused tenant even when the provider names no finding',
            {
                aws: { health: 'critical', sending_status: 'DISABLED', findings: [] },
                reputation: { bounce_rate: 0.067, complaint_rate: 0.004, emails_sent: 300 },
                workflows: MANY_SMALL,
            },
            [
                { key: 'provider-status', severity: 'high', blocksSending: true },
                { key: 'project-bounce', severity: 'high', blocksSending: false },
            ],
        ],
        [
            // Only support can lift a pause, so the findings that explain it do not replace the row.
            'flags a paused tenant above the findings that explain it',
            { aws: { health: 'critical', sending_status: 'DISABLED', findings: [finding('BOUNCE', 'HIGH')] } },
            [
                { key: 'provider-status', severity: 'high', blocksSending: true },
                { key: 'finding:BOUNCE', severity: 'high', blocksSending: false },
            ],
        ],
        [
            'flags a warning verdict with no finding',
            { aws: { health: 'warning', sending_status: 'ENABLED', findings: [] } },
            [{ key: 'provider-status', severity: 'medium', blocksSending: false }],
        ],
        [
            'flags a PostHog suspension',
            { email_sending_suspended: true },
            [{ key: 'project-suspended', severity: 'high', blocksSending: true }],
        ],
        [
            'flags a paused workflow as blocking its email',
            {
                workflows: [
                    workflow('win-back', { emails_sent: 400, bounce_rate: 0.08, complaint_rate: 0 }, 'Paused.'),
                ],
            },
            [{ key: 'paused:win-back', severity: 'high', blocksSending: true }],
        ],
        [
            'ranks complaints over bounces and optional DNS work last',
            {
                ...flagged(finding('BIMI', 'LOW'), finding('DMARC', 'LOW')),
                reputation: { bounce_rate: 0.1, complaint_rate: 0.002, emails_sent: 3000 },
                workflows: [
                    workflow('bouncy', { emails_sent: 1000, bounce_rate: 0.3, complaint_rate: 0 }),
                    workflow('spammy', { emails_sent: 2000, bounce_rate: 0, complaint_rate: 0.008 }),
                ],
            },
            [
                { key: 'workflow-complaint:spammy', severity: 'high', blocksSending: false },
                { key: 'workflow-bounce:bouncy', severity: 'high', blocksSending: false },
                { key: 'finding:DMARC', severity: 'medium', blocksSending: false },
                { key: 'finding:BIMI', severity: 'low', blocksSending: false },
            ],
        ],
        [
            'ranks the workflow furthest over a line first',
            {
                reputation: { bounce_rate: 0.04, complaint_rate: 0, emails_sent: 2000 },
                workflows: [
                    workflow('a', { emails_sent: 1000, bounce_rate: 0.035, complaint_rate: 0 }),
                    workflow('b', { emails_sent: 1000, bounce_rate: 0.045, complaint_rate: 0 }),
                ],
            },
            [
                { key: 'workflow-bounce:b', severity: 'medium', blocksSending: false },
                { key: 'workflow-bounce:a', severity: 'medium', blocksSending: false },
            ],
        ],
        [
            'keeps the provider order for findings that tie',
            flagged(finding('IP_LISTING', 'HIGH'), finding('DKIM', 'HIGH')),
            [
                { key: 'finding:IP_LISTING', severity: 'high', blocksSending: false },
                { key: 'finding:DKIM', severity: 'high', blocksSending: false },
            ],
        ],
        [
            // A tenant can hold two findings of one type, for example DKIM on two domains.
            'gives a repeated finding its own key',
            flagged(finding('DKIM', 'HIGH'), finding('DKIM', 'LOW')),
            [
                { key: 'finding:DKIM', severity: 'high', blocksSending: false },
                { key: 'finding:DKIM:2', severity: 'medium', blocksSending: false },
            ],
        ],
    ])('%s', (_, overrides, expected) => {
        const actions = build(overrides)

        expect(actions.map(({ key, severity, blocksSending }) => ({ key, severity, blocksSending }))).toEqual(expected)
    })

    // Clicks an on-page button against a recording page, so a case names where the click lands.
    function clickTarget(onClick: (page: ReputationPageControls) => void): string {
        const landed: string[] = []
        onClick({
            openSupportForm: () => landed.push('support form'),
            showBreakdown: (tab) => landed.push(`${tab} tab`),
        })
        return landed.join(', ')
    }

    function targets(action: ReputationAction | undefined): { button?: string; docs?: string } | undefined {
        if (!action) {
            return undefined
        }
        const cta = action.cta
        const button = cta && (cta.onClick ? clickTarget(cta.onClick) : cta.to)
        return { button, docs: action.docsLink?.to }
    }
    const openWorkflow = (id: string): string => `${urls.workflow(id, 'workflow')}?node=trigger_node`
    const optOuts = urls.workflows('opt-outs')
    const BOUNCY = workflow('bouncy', { emails_sent: 1000, bounce_rate: 0.3, complaint_rate: 0 })
    const SPAMMY = workflow('spammy', { emails_sent: 2000, bounce_rate: 0, complaint_rate: 0.008 })
    const QUIET = workflow('quiet', { emails_sent: 8000, bounce_rate: 0.004, complaint_rate: 0.0002 })
    const IMPORT = workflow('import', { emails_sent: 1500, bounce_rate: 0.06, complaint_rate: 0 })

    it.each<[string, string, Overrides, { button?: string; docs?: string }]>([
        ['a PostHog suspension', 'project-suspended', { email_sending_suspended: true }, { button: 'support form' }],
        [
            'a provider pause',
            'provider-status',
            { aws: { health: 'critical', sending_status: 'DISABLED', findings: [] } },
            { button: 'support form', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a provider warning',
            'provider-status',
            { aws: { health: 'warning', sending_status: 'ENABLED', findings: [] } },
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a paused workflow',
            'paused:win-back',
            {
                workflows: [
                    workflow('win-back', { emails_sent: 400, bounce_rate: 0.08, complaint_rate: 0 }, 'Paused.'),
                ],
            },
            { button: openWorkflow('win-back'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a bounce finding one workflow causes',
            'finding:BOUNCE',
            {
                ...flagged(finding('BOUNCE', 'HIGH')),
                reputation: { bounce_rate: 0.0263, complaint_rate: 0, emails_sent: 9500 },
                workflows: [QUIET, IMPORT],
            },
            { button: openWorkflow('import'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            // The tiny workflow causes most bounces, but 10 sends is under the volume floor.
            'a bounce finding whose worst workflow is too small to blame',
            'finding:BOUNCE',
            {
                ...flagged(finding('BOUNCE', 'HIGH')),
                reputation: { bounce_rate: 0.005, complaint_rate: 0, emails_sent: 1000 },
                workflows: [
                    workflow('big', { emails_sent: 990, bounce_rate: 0.002, complaint_rate: 0 }),
                    workflow('tiny', { emails_sent: 10, bounce_rate: 0.3, complaint_rate: 0 }),
                ],
            },
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            // The biggest sender is barely above average, so its share of bounces tracks its share of sends.
            'a bounce finding whose worst workflow is only the biggest sender',
            'finding:BOUNCE',
            {
                ...flagged(finding('BOUNCE', 'HIGH')),
                reputation: { bounce_rate: 0.02, complaint_rate: 0, emails_sent: 10000 },
                workflows: [
                    workflow('big', { emails_sent: 6000, bounce_rate: 0.021, complaint_rate: 0 }),
                    workflow('small', { emails_sent: 4000, bounce_rate: 0.0185, complaint_rate: 0 }),
                ],
            },
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            // The paused workflow has its own row, so the finding names the next worst one.
            'a bounce finding whose worst workflow is paused',
            'finding:BOUNCE',
            {
                ...flagged(finding('BOUNCE', 'HIGH')),
                reputation: { bounce_rate: 0.03, complaint_rate: 0, emails_sent: 10000 },
                workflows: [
                    workflow('paused', { emails_sent: 2000, bounce_rate: 0.1, complaint_rate: 0 }, 'Paused.'),
                    workflow('next', { emails_sent: 2000, bounce_rate: 0.05, complaint_rate: 0 }),
                    workflow('rest', { emails_sent: 6000, bounce_rate: 0.01, complaint_rate: 0 }),
                ],
            },
            { button: openWorkflow('next'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a complaint finding one workflow causes',
            'finding:COMPLAINT',
            {
                ...flagged(finding('COMPLAINT', 'HIGH')),
                reputation: { bounce_rate: 0.003, complaint_rate: 0.00176, emails_sent: 10000 },
                workflows: [QUIET, SPAMMY],
            },
            { button: openWorkflow('spammy'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a complaint finding no workflow causes',
            'finding:COMPLAINT',
            flagged(finding('COMPLAINT', 'HIGH')),
            { button: optOuts, docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a DNS finding',
            'finding:DKIM',
            flagged(finding('DKIM', 'HIGH')),
            { button: urls.workflows('channels'), docs: CHANNEL_SETUP_DOCS_URL },
        ],
        ['a BIMI finding', 'finding:BIMI', flagged(finding('BIMI', 'LOW')), {}],
        [
            'a blocklist finding',
            'finding:IP_LISTING',
            flagged(finding('IP_LISTING', 'HIGH')),
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a project bounce rate from many small workflows',
            'project-bounce',
            { reputation: { bounce_rate: 0.067, complaint_rate: 0, emails_sent: 300 }, workflows: MANY_SMALL },
            { button: 'workflows tab', docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a project complaint rate from many small workflows',
            'project-complaint',
            { reputation: { bounce_rate: 0.004, complaint_rate: 0.004, emails_sent: 3000 }, workflows: MANY_SMALL },
            { button: optOuts, docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a workflow over the bounce line',
            'workflow-bounce:bouncy',
            { workflows: [BOUNCY] },
            { button: openWorkflow('bouncy'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a workflow over the complaint line',
            'workflow-complaint:spammy',
            { workflows: [SPAMMY] },
            { button: openWorkflow('spammy'), docs: LOWER_RATES_DOCS_URL },
        ],
        [
            'a mailbox provider over the bounce line',
            'provider-bounce:Yahoo',
            { isps: [YAHOO_BOUNCING] },
            { button: 'providers tab', docs: LOWER_RATES_DOCS_URL },
        ],
    ])('points %s at the page that fixes it', (_, key, overrides, expected) => {
        const action = build(overrides).find((item) => item.key === key)

        expect(targets(action)).toEqual(expected)
    })

    it.each(
        Object.values(FindingTypeEnumApi).flatMap((type) => [
            [type, 'HIGH' as const, type === 'BIMI' ? 'low' : 'high'],
            [type, 'LOW' as const, type === 'BIMI' ? 'low' : 'medium'],
        ])
    )('shows exactly one row for a %s finding with %s impact', (findingType, impact, severity) => {
        const actions = build(flagged(finding(findingType, impact)))

        expect(actions.map(({ key, severity }) => ({ key, severity }))).toEqual([
            { key: `finding:${findingType}`, severity },
        ])
    })

    it('says when a provider row counts email from other projects', () => {
        const [providerAction] = build({ isps: [YAHOO_BOUNCING], isp_shared_domains: ['mail.example.com'] })

        expect(providerAction.key).toEqual('provider-bounce:Yahoo')
        expect(providerAction.description).toContain('mail.example.com')
    })

    it('registers every action definition under its own kind', async () => {
        const files = readdirSync(join(__dirname, 'definitions'))
        const modules: Record<string, unknown>[] = await Promise.all(
            files.map((file) => import(`./definitions/${file}`))
        )
        const defined = modules
            .flatMap((module) => Object.values(module))
            .filter(
                (value): value is RegisteredReputationAction => typeof value === 'object' && !!value && 'build' in value
            )

        expect(defined.filter((action) => REPUTATION_ACTIONS[action.kind] !== action).map(({ kind }) => kind)).toEqual(
            []
        )
        expect(defined).toHaveLength(Object.keys(REPUTATION_ACTIONS).length)
    })
})
