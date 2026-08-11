import { SignalSourceProduct } from '../../../types'

/**
 * Shared fixture and prop contract for the Signal sources design lab.
 *
 * THROWAWAY, and deliberately not committed. Rebuilt for a demo of the design round.
 *
 * Every variant renders from this data and nothing else, so the grid compares design rather than
 * fixtures. The data is invented, not copied from any project.
 */

export type LabSourceKey =
    | 'error_tracking'
    | 'conversations'
    | 'replay_vision'
    | 'session_replay'
    | 'llm_analytics'
    | 'analytics'
    | 'health_checks'
    | 'github'
    | 'linear'
    | 'zendesk'
    | 'pganalyze'

export type LabStatus = 'standby' | 'watching' | 'syncing' | 'sync_failed'

/** One individually controllable thing inside a source: a scanner, an evaluation, a signal type. */
export interface LabEntity {
    id: string
    name: string
    /** One line of detail. Long on purpose in places, so truncation shows up in the grid. */
    detail?: string
    /** This entity feeds the inbox. */
    enabled: boolean
    /** Small tag: the scanner type, the evaluation type, the repository visibility. */
    kind?: string
    /** Set when the system turned it off, so the row explains itself rather than looking user-set. */
    systemNote?: string
}

/** A setting that is not a child entity: one control that applies to the whole source. */
export interface LabSetting {
    key: string
    label: string
    help?: string
    control: 'switch' | 'select' | 'number'
    value: string | number | boolean
    options?: { value: string; label: string }[]
    suffix?: string
}

export interface LabTool {
    name: string
    enabled: boolean
    /** null when the source has no cheap way to tell. */
    receivingData: boolean | null
}

export interface LabSource {
    key: LabSourceKey
    label: string
    description: string
    group: 'PostHog data' | 'External sources'
    /** Drives the real icon through `getSourceProductMeta`. */
    product: SignalSourceProduct
    armed: boolean
    status: LabStatus
    alpha?: boolean
    legacy?: boolean
    docsUrl?: string
    docsLabel?: string
    tool?: LabTool
    /** Warehouse-backed source with no connection yet: shows Connect instead of a switch. */
    requiresSetup?: boolean
    /** Individually controllable children. Undefined means the source has none. */
    entities?: LabEntity[]
    /** Plural noun for the children, for copy like "2 of 3 scanners watching". */
    entityNoun?: string
    /** Singular noun, for the add affordance. */
    entityNounSingular?: string
    /** Where a user goes to create a new child. */
    entityManageUrl?: string
    /** Source-wide settings, inlined next to the entities. */
    settings?: LabSetting[]
}

export type LabScenario = 'typical' | 'heavy' | 'nothingOn' | 'toolsOff'

export interface VariantProps {
    sources: LabSource[]
    scenario: LabScenario
}

/** Panel width each variant asks the modal for. The grid frames the tile at this width. */
export const DEFAULT_PANEL_WIDTH = 760

const ERROR_TRACKING_TYPES: LabEntity[] = [
    { id: 'issue_created', name: 'New issue', detail: 'An error that has not been seen before.', enabled: true },
    { id: 'issue_reopened', name: 'Reopened issue', detail: 'A resolved issue that came back.', enabled: true },
    {
        id: 'issue_spiking',
        name: 'Spiking issue',
        detail: 'A known issue whose rate jumped well above its baseline.',
        enabled: false,
    },
]

const SCANNERS_TYPICAL: LabEntity[] = [
    {
        id: 'sc-1',
        name: 'Checkout confusion',
        detail: 'Watches for hesitation and repeated attempts on the checkout step.',
        enabled: true,
        kind: 'Monitor',
    },
    {
        id: 'sc-2',
        name: 'Rage clicks on the pricing page',
        detail: 'Flags repeated clicks on elements that do not respond.',
        enabled: true,
        kind: 'Monitor',
    },
    {
        id: 'sc-3',
        name: 'Onboarding drop-off classifier with a deliberately long name',
        detail: 'Sorts abandoned onboarding sessions into reasons.',
        enabled: false,
        kind: 'Classifier',
    },
]

const EVALUATIONS_TYPICAL: LabEntity[] = [
    {
        id: 'ev-1',
        name: 'Answer grounded in context',
        detail: 'Fails when the reply states something the retrieved context does not support.',
        enabled: true,
        kind: 'LLM judge',
    },
    {
        id: 'ev-2',
        name: 'Refusal rate',
        detail: 'Counts replies that decline a question the product should answer.',
        enabled: true,
        kind: 'Hog',
    },
    {
        id: 'ev-3',
        name: 'User sentiment',
        detail: 'Classifies the sentiment of the user turns in a trace.',
        enabled: false,
        kind: 'Sentiment',
    },
    {
        id: 'ev-4',
        name: 'Tool call validity',
        enabled: false,
        kind: 'Hog',
        systemNote: 'Turned off automatically after 5 failed runs.',
    },
]

function manyScanners(count: number): LabEntity[] {
    const stems = [
        'Checkout confusion',
        'Rage clicks',
        'Search with no results',
        'Form abandonment',
        'Paywall hesitation',
        'Mobile nav confusion',
        'Signup friction',
        'Dashboard load stall',
    ]
    return Array.from({ length: count }, (_, i) => ({
        id: `sc-many-${i}`,
        name: `${stems[i % stems.length]} ${Math.floor(i / stems.length) + 1}`,
        detail: 'Watches recordings for one specific failure pattern.',
        enabled: i % 3 !== 2,
        kind: i % 4 === 0 ? 'Classifier' : 'Monitor',
    }))
}

function baseSources(): LabSource[] {
    return [
        {
            key: 'error_tracking',
            label: 'Error tracking',
            description: 'Bugs surfaced as new errors, regressions, and spikes.',
            group: 'PostHog data',
            product: SignalSourceProduct.ErrorTracking,
            armed: true,
            status: 'watching',
            docsUrl: 'https://posthog.com/docs/error-tracking',
            docsLabel: 'Error tracking',
            tool: { name: 'Error tracking', enabled: true, receivingData: true },
            entities: ERROR_TRACKING_TYPES,
            entityNoun: 'signal types',
            entityNounSingular: 'signal type',
            settings: [
                {
                    key: 'min_volume',
                    label: 'Minimum events',
                    help: 'Ignore an issue until it happens this many times.',
                    control: 'number',
                    value: 25,
                },
            ],
        },
        {
            key: 'replay_vision',
            label: 'Replay vision',
            description: 'Bugs and UX problems scanners find while watching recordings.',
            group: 'PostHog data',
            product: SignalSourceProduct.ReplayVision,
            armed: true,
            status: 'watching',
            docsUrl: 'https://posthog.com/docs/replay-vision',
            docsLabel: 'Replay vision',
            tool: { name: 'Session replay', enabled: true, receivingData: null },
            entities: SCANNERS_TYPICAL,
            entityNoun: 'scanners',
            entityNounSingular: 'scanner',
            entityManageUrl: '/replay/vision',
        },
        {
            key: 'llm_analytics',
            label: 'AI observability',
            description: 'Quality problems in your AI features, found by your evaluations.',
            group: 'PostHog data',
            product: SignalSourceProduct.LlmAnalytics,
            armed: true,
            status: 'watching',
            docsUrl: 'https://posthog.com/docs/ai-evals',
            docsLabel: 'evaluations',
            tool: { name: 'LLM analytics', enabled: true, receivingData: true },
            entities: EVALUATIONS_TYPICAL,
            entityNoun: 'evaluations',
            entityNounSingular: 'evaluation',
            entityManageUrl: '/llm-analytics/evaluations',
        },
        {
            key: 'session_replay',
            label: 'Session replay',
            description: 'UX problems found in session recordings. Replay vision covers this now.',
            group: 'PostHog data',
            product: SignalSourceProduct.SessionReplay,
            armed: false,
            status: 'standby',
            legacy: true,
            docsUrl: 'https://posthog.com/docs/session-replay',
            docsLabel: 'Session replay',
            tool: { name: 'Session replay', enabled: true, receivingData: null },
            settings: [
                {
                    key: 'sample',
                    label: 'Sessions analyzed',
                    help: 'Share of matching recordings each run looks at.',
                    control: 'number',
                    value: 10,
                    suffix: '%',
                },
            ],
        },
        {
            key: 'conversations',
            label: 'Support',
            description: 'Problems customers raise in support.',
            group: 'PostHog data',
            product: SignalSourceProduct.Conversations,
            armed: false,
            status: 'standby',
            docsUrl: 'https://posthog.com/docs/support',
            docsLabel: 'Support',
            tool: { name: 'Support', enabled: false, receivingData: null },
        },
        {
            key: 'analytics',
            label: 'Product analytics',
            description: 'Anomalies and unexpected shifts detected in your product metrics.',
            group: 'PostHog data',
            product: SignalSourceProduct.Analytics,
            armed: false,
            status: 'standby',
            alpha: true,
            docsUrl: 'https://posthog.com/docs/product-analytics',
            docsLabel: 'Product analytics',
            tool: { name: 'Product analytics', enabled: true, receivingData: true },
        },
        {
            key: 'health_checks',
            label: 'Health checks',
            description: 'Instrumentation issues - missing events, proxy gaps, and outdated SDKs.',
            group: 'PostHog data',
            product: SignalSourceProduct.HealthChecks,
            armed: true,
            status: 'watching',
        },
        {
            key: 'github',
            label: 'GitHub Issues',
            description: 'Issues filed in GitHub.',
            group: 'External sources',
            product: SignalSourceProduct.Github,
            armed: true,
            status: 'syncing',
            entities: [
                { id: 'r1', name: 'acme/web', detail: 'Synced 4 minutes ago.', enabled: true, kind: 'Private' },
                { id: 'r2', name: 'acme/mobile', detail: 'Synced 4 minutes ago.', enabled: true, kind: 'Private' },
                { id: 'r3', name: 'acme/docs', detail: 'Synced 4 minutes ago.', enabled: false, kind: 'Public' },
            ],
            entityNoun: 'repositories',
            entityNounSingular: 'repository',
        },
        {
            key: 'linear',
            label: 'Linear',
            description: 'Issues tracked in Linear.',
            group: 'External sources',
            product: SignalSourceProduct.Linear,
            armed: false,
            status: 'standby',
            requiresSetup: true,
        },
        {
            key: 'zendesk',
            label: 'Zendesk',
            description: 'Incoming Zendesk tickets.',
            group: 'External sources',
            product: SignalSourceProduct.Zendesk,
            armed: false,
            status: 'standby',
            requiresSetup: true,
        },
        {
            key: 'pganalyze',
            label: 'pganalyze',
            description: 'Postgres performance problems, including slow queries and bad indexes.',
            group: 'External sources',
            product: SignalSourceProduct.Pganalyze,
            armed: false,
            status: 'sync_failed',
            requiresSetup: false,
        },
    ]
}

export function sourcesFor(scenario: LabScenario): LabSource[] {
    const sources = baseSources()
    if (scenario === 'heavy') {
        return sources.map((source) =>
            source.key === 'replay_vision' ? { ...source, entities: manyScanners(63) } : source
        )
    }
    if (scenario === 'nothingOn') {
        return sources.map((source) => ({
            ...source,
            armed: false,
            status: 'standby' as LabStatus,
            entities: source.entities?.map((entity) => ({ ...entity, enabled: false, systemNote: undefined })),
        }))
    }
    if (scenario === 'toolsOff') {
        return sources.map((source) => ({
            ...source,
            tool: source.tool ? { ...source.tool, enabled: false } : undefined,
        }))
    }
    return sources
}

export const LAB_GROUPS: LabSource['group'][] = ['PostHog data', 'External sources']

/** Count of children feeding the inbox, for the "2 of 3 scanners" line every variant shows. */
export function enabledEntityCount(source: LabSource): number {
    return source.entities?.filter((entity) => entity.enabled).length ?? 0
}

/** True when the source is on because at least one child is on, rather than a source-level switch. */
export function isEntityDriven(source: LabSource): boolean {
    return source.key === 'replay_vision' || source.key === 'llm_analytics'
}
