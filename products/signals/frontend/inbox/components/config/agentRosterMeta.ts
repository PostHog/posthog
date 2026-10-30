import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { urls } from 'scenes/urls'

import { EXTERNAL_SIGNAL_SOURCES, ExternalSignalSource } from '../../externalSignalSources'
import { SignalSourceProduct } from '../../types'

/**
 * Stable string keys for the agent roster, aligned with the source-product
 * strings the backend uses. These drive icon lookup via `getSourceProductMeta`
 * and the per-source wiring in `AgentsRoster`.
 */
export type AgentRosterSource =
    | 'error_tracking'
    | 'conversations'
    | 'replay_vision'
    | 'llm_analytics'
    | 'analytics'
    | 'health_checks'
    | ExternalSignalSource
    | 'engineering_analytics'

export interface AgentRosterDefinition {
    source: AgentRosterSource
    /** Key into `SOURCE_PRODUCT_META` for the icon tile. */
    sourceProduct: SignalSourceProduct
    label: string
    category?: string
    /** The tagline: one truncated line under the source name, saying what this source watches. */
    watches: string
    /**
     * The line the expansion opens with. It must add something the tagline does not say, usually
     * what triggers a signal or what the source needs, never a restatement of what it watches.
     */
    detail?: string
    /** Plural noun for the things listed inside this source, e.g. "scanners". */
    entityNoun?: string
    /**
     * The entities are created by the user, so the list has no fixed length. Such a source gets no
     * row-level switch: a master over an unbounded list is a bulk mutation of things we did not
     * define. A fixed, product-defined list (error tracking's three signal types) keeps its master.
     */
    entitiesAreUserCreated?: boolean
    /** Singular of `entityNoun`, for the "New scanner" button. */
    entityNounSingular?: string
    docsUrl?: string
    docsLabel?: string
    alpha?: boolean
    /** Superseded by another source. Tagged and dimmed so it reads as the older option. */
    legacy?: boolean
    /**
     * Scene that owns this source's on/off state, for sources with no `SignalSourceConfig` row to
     * toggle. The card links there instead of showing a switch.
     */
    manageUrl?: string
    /**
     * An actionability gate runs on this source's records and reads the steering keys on
     * `SignalSourceConfig.config` (see `sourceSteeringModalLogic`). Either the emission pipeline's
     * gate, or, for a source that emits directly, the one listing it in the backend's
     * `DIRECT_STEERABLE_SOURCES`. Sources without a gate must not offer the steering form: the keys
     * would be stored but nothing would read them.
     */
    steerable?: boolean
    /** Show this entry only while the given feature flag is enabled (alpha rollouts). */
    flag?: FeatureFlagKey
}

export interface AgentRosterGroup {
    id: 'posthog' | 'external'
    label: string
    agents: AgentRosterDefinition[]
}

export const AGENT_ROSTER_GROUPS: AgentRosterGroup[] = [
    {
        id: 'posthog',
        label: 'PostHog data',
        agents: [
            {
                source: 'error_tracking',
                sourceProduct: SignalSourceProduct.ErrorTracking,
                label: 'Error tracking',
                watches: 'New errors, regressions, and spikes in your app',
                detail: 'Each type below is a separate trigger, so turning one off leaves the others watching.',
                entityNoun: 'signal types',
                entityNounSingular: 'signal type',
                steerable: true,
                docsUrl: 'https://posthog.com/docs/error-tracking',
                docsLabel: 'Error tracking',
            },
            {
                source: 'conversations',
                sourceProduct: SignalSourceProduct.Conversations,
                label: 'Support',
                watches: 'Problems customers raise in support',
                detail: 'Only open tickets are read.',
                steerable: true,
                docsUrl: 'https://posthog.com/docs/support',
                docsLabel: 'Support',
            },
            {
                source: 'replay_vision',
                sourceProduct: SignalSourceProduct.ReplayVision,
                label: 'Replay vision',
                watches: 'UX problems your scanners find while watching recordings',
                detail: 'Switching a scanner on here lets its findings start agent research. Scouts read observations from any scanner either way.',
                entityNoun: 'scanners',
                entityNounSingular: 'scanner',
                entitiesAreUserCreated: true,
                docsUrl: 'https://posthog.com/docs/replay-vision',
                docsLabel: 'Replay vision',
                manageUrl: urls.replayVision(),
            },
            {
                source: 'llm_analytics',
                sourceProduct: SignalSourceProduct.LlmAnalytics,
                label: 'AI observability',
                watches: 'Changes in the quality and behavior of your AI features',
                detail: 'Completed eval reports can become signals for agent investigation. Configure which reports run and when in AI observability.',
                docsUrl: 'https://posthog.com/docs/ai-observability/self-driving',
                docsLabel: 'AI observability Self-driving',
            },
            {
                source: 'analytics',
                sourceProduct: SignalSourceProduct.Analytics,
                label: 'Product analytics',
                watches: 'Unexpected shifts in your product metrics',
                detail: 'Fires when an anomaly alert goes off, and only for the alerts where you turned the investigation agent on.',
                docsUrl: 'https://posthog.com/docs/product-analytics',
                docsLabel: 'Product analytics',
                alpha: true,
            },
            {
                source: 'health_checks',
                sourceProduct: SignalSourceProduct.HealthChecks,
                label: 'Health checks',
                watches: 'Missing events, proxy gaps, and outdated SDKs',
                detail: 'Checks your setup for missing events, an outdated SDK, proxy problems, failed warehouse syncs, and missing source maps.',
                steerable: true,
                docsUrl: urls.health(),
                docsLabel: 'Health checks',
            },
        ],
    },
    {
        id: 'external',
        label: 'External sources',
        agents: [
            ...EXTERNAL_SIGNAL_SOURCES.map((source) => ({
                source: source.source,
                sourceProduct: source.source,
                label: source.label,
                category: source.category,
                watches: source.watches,
                detail: `Reads the ${source.label} data you sync to Data warehouse.`,
                steerable: true,
            })),
            {
                source: 'engineering_analytics',
                sourceProduct: SignalSourceProduct.EngineeringAnalytics,
                label: 'GitHub CI',
                category: 'Engineering',
                watches: 'Flaky checks and slowing GitHub Actions workflows',
                detail: 'Reads workflow runs and pull requests from the GitHub repositories you sync.',
                alpha: true,
                flag: FEATURE_FLAGS.ENGINEERING_ANALYTICS,
            },
        ],
    },
]
