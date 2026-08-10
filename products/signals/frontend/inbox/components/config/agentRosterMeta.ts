import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { urls } from 'scenes/urls'

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
    | 'session_replay'
    | 'llm_analytics'
    | 'analytics'
    | 'health_checks'
    | 'github'
    | 'linear'
    | 'zendesk'
    | 'pganalyze'
    | 'engineering_analytics'

export interface AgentRosterDefinition {
    source: AgentRosterSource
    /** Key into `SOURCE_PRODUCT_META` for the icon tile. */
    sourceProduct: SignalSourceProduct
    label: string
    description: string
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
    /** Show this entry only while the given feature flag is enabled (alpha rollouts). */
    flag?: FeatureFlagKey
}

export interface AgentRosterGroup {
    label: string
    agents: AgentRosterDefinition[]
}

export const AGENT_ROSTER_GROUPS: AgentRosterGroup[] = [
    {
        label: 'PostHog data',
        agents: [
            {
                source: 'error_tracking',
                sourceProduct: SignalSourceProduct.ErrorTracking,
                label: 'Error tracking',
                description: 'Bugs surfaced as new errors, regressions, and spikes.',
                docsUrl: 'https://posthog.com/docs/error-tracking',
                docsLabel: 'Error tracking',
            },
            {
                source: 'conversations',
                sourceProduct: SignalSourceProduct.Conversations,
                label: 'Support',
                description: 'Problems customers raise in support.',
                docsUrl: 'https://posthog.com/docs/support',
                docsLabel: 'Support',
            },
            {
                source: 'replay_vision',
                sourceProduct: SignalSourceProduct.ReplayVision,
                label: 'Replay vision',
                description: 'Bugs and UX problems scanners find while watching recordings.',
                docsUrl: 'https://posthog.com/docs/replay-vision',
                docsLabel: 'Replay vision',
                manageUrl: urls.replayVision(),
            },
            {
                source: 'session_replay',
                sourceProduct: SignalSourceProduct.SessionReplay,
                label: 'Session replay',
                description: 'UX problems found in session recordings. Replay vision covers this now.',
                docsUrl: 'https://posthog.com/docs/session-replay',
                docsLabel: 'Session replay',
                legacy: true,
            },
            {
                source: 'llm_analytics',
                sourceProduct: SignalSourceProduct.LlmAnalytics,
                label: 'AI observability',
                description: 'Quality problems in your AI features. Set up evaluations to start getting signals.',
                docsUrl: 'https://posthog.com/docs/ai-evals',
                docsLabel: 'evaluations',
            },
            {
                source: 'analytics',
                sourceProduct: SignalSourceProduct.Analytics,
                label: 'Product analytics',
                description: 'Anomalies and unexpected shifts detected in your product metrics.',
                docsUrl: 'https://posthog.com/docs/product-analytics',
                docsLabel: 'Product analytics',
                alpha: true,
            },
            {
                source: 'health_checks',
                sourceProduct: SignalSourceProduct.HealthChecks,
                label: 'Health checks',
                description: 'Instrumentation issues - missing events, proxy gaps, and outdated SDKs.',
            },
        ],
    },
    {
        label: 'External sources',
        agents: [
            {
                source: 'github',
                sourceProduct: SignalSourceProduct.Github,
                label: 'GitHub Issues',
                description: 'Issues filed in GitHub.',
            },
            {
                source: 'engineering_analytics',
                sourceProduct: SignalSourceProduct.EngineeringAnalytics,
                label: 'GitHub CI',
                description: 'Flaky checks, broken default branch, and slowing workflows in GitHub Actions.',
                alpha: true,
                flag: FEATURE_FLAGS.ENGINEERING_ANALYTICS,
            },
            {
                source: 'linear',
                sourceProduct: SignalSourceProduct.Linear,
                label: 'Linear',
                description: 'Issues tracked in Linear.',
            },
            {
                source: 'zendesk',
                sourceProduct: SignalSourceProduct.Zendesk,
                label: 'Zendesk',
                description: 'Incoming Zendesk tickets.',
            },
            {
                source: 'pganalyze',
                sourceProduct: SignalSourceProduct.Pganalyze,
                label: 'pganalyze',
                description: 'Postgres performance problems, including slow queries and bad indexes.',
            },
        ],
    },
]
