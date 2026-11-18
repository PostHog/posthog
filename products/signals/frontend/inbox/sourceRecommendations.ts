import type { AgentRosterDefinition, AgentRosterSource } from './components/config/agentRosterMeta'
import type { ExternalSignalSource } from './externalSignalSources'

export type SourceRecommendationReason = 'synced' | 'integration' | 'default'

export interface SourceRecommendation {
    agent: AgentRosterDefinition
    reason: SourceRecommendationReason
    description?: string
}

export interface SourceRecommendationInput {
    source: AgentRosterSource
    connected: boolean
    enabled: boolean
    /** An explicit saved rejection should not become a recommendation. */
    declinedInOnboarding?: boolean
}

export const DEFAULT_RECOMMENDATIONS: readonly { source: AgentRosterSource; description: string }[] = [
    { source: 'github', description: 'Issues filed in GitHub' },
    { source: 'engineering_analytics', description: 'Flaky checks and slowing GitHub Actions workflows' },
    { source: 'linear', description: 'Issues tracked in Linear' },
    { source: 'zendesk', description: 'Incoming Zendesk tickets' },
]

/**
 * A PostHog product that covers a catalog category. While it is on, external tools in that category
 * are not suggested: a team watching Error tracking does not need to hear about Sentry.
 */
export const POSTHOG_SOURCE_CATEGORIES: Partial<Record<AgentRosterSource, string>> = {
    error_tracking: 'Error tracking',
    conversations: 'Support',
}

export const INTEGRATION_KIND_SOURCES: Readonly<Record<string, ExternalSignalSource>> = {
    github: 'github',
    gitlab: 'gitlab',
    intercom: 'intercom',
    jira: 'jira',
    linear: 'linear',
    hubspot: 'hubspot',
    'google-search-console': 'google_search_console',
}

export const MAX_SOURCE_RECOMMENDATIONS = 4

export function recommendSources(
    agents: AgentRosterDefinition[],
    states: SourceRecommendationInput[],
    integrationKinds: readonly string[]
): SourceRecommendation[] {
    const stateBySource = new Map(states.map((state) => [state.source, state]))
    const agentBySource = new Map(agents.map((agent) => [agent.source, agent]))
    const coveredCategories = new Set(
        states
            .filter((state) => state.enabled)
            .map((state) => POSTHOG_SOURCE_CATEGORIES[state.source])
            .filter((category): category is string => !!category)
    )
    const recommendations: SourceRecommendation[] = []
    const add = (source: AgentRosterSource, reason: SourceRecommendationReason, description?: string): void => {
        const agent = agentBySource.get(source)
        const state = stateBySource.get(source)
        if (
            !agent ||
            !state ||
            state.enabled ||
            state.declinedInOnboarding ||
            (agent.category && coveredCategories.has(agent.category)) ||
            recommendations.some((existing) => existing.agent.source === source)
        ) {
            return
        }
        recommendations.push({ agent, reason, description })
    }

    for (const state of states) {
        if (state.connected) {
            add(state.source, 'synced')
        }
    }
    for (const kind of integrationKinds) {
        const source = INTEGRATION_KIND_SOURCES[kind]
        if (source && !stateBySource.get(source)?.connected) {
            add(source, 'integration')
        }
    }
    // Adding one external tool proves the person found the catalog, so the generic defaults have done
    // their job. The two project-specific reasons above stay: they are cheap and about this project.
    const hasExternalSource = agents.some((agent) => {
        const state = stateBySource.get(agent.source)
        return !!state && (state.connected || state.enabled)
    })
    if (!hasExternalSource) {
        for (const { source, description } of DEFAULT_RECOMMENDATIONS) {
            add(source, 'default', description)
        }
    }
    return recommendations
}
