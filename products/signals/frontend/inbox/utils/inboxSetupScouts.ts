import type {
    InboxOnboardingDraftApi,
    ScoutSuggestionItemApi,
    SelfDrivingTrialStatusApi,
    SignalScoutConfigApi,
} from '../../generated/api.schemas'
import type { AgentRosterSource } from '../components/config/agentRosterMeta'
import type { SourceProductStatus } from '../signalSourcesLogic'
import type { InboxSetupSource } from './inboxSetup'

interface StarterScout {
    name: string
    source: AgentRosterSource | 'session_replay' | 'general'
    title: string
    description: string
}

const STARTER_SCOUTS: StarterScout[] = [
    {
        name: 'signals-scout-general',
        source: 'general',
        title: 'General scout',
        description:
            'Explore available project data, connect patterns across products, and investigate what needs attention.',
    },
    {
        name: 'signals-scout-product-analytics',
        source: 'analytics',
        title: 'Monitor funnel drop-offs',
        description: 'Investigate changes in funnel conversion, retention, and how customers use your product.',
    },
    {
        name: 'signals-scout-error-tracking',
        source: 'error_tracking',
        title: 'Investigate recurring errors',
        description: 'Look for error patterns, regressions, and groups of failures affecting customers.',
    },
    {
        name: 'signals-scout-session-replay',
        source: 'session_replay',
        title: 'Find friction in session recordings',
        description: 'Watch for recording gaps, rage clicks, dead clicks, and recurring usability problems.',
    },
    {
        name: 'signals-scout-replay-vision',
        source: 'replay_vision',
        title: 'Monitor usability problems',
        description: 'Follow recurring themes and changes found by your Replay Vision scanners.',
    },
    {
        name: 'signals-scout-ai-observability',
        source: 'llm_analytics',
        title: 'Monitor AI cost and reliability',
        description: 'Investigate changes in LLM costs, latency, errors, and output quality.',
    },
    {
        name: 'signals-scout-conversations',
        source: 'conversations',
        title: 'Monitor support response times',
        description: 'Look for slow first responses, growing backlogs, and missed support targets.',
    },
    {
        name: 'signals-scout-health-checks',
        source: 'health_checks',
        title: 'Investigate setup health issues',
        description: 'Group related health checks and identify the setup problems worth fixing.',
    },
]

export function inboxSetupScoutCopy(skillName: string): { title: string; description: string } | undefined {
    const starter = STARTER_SCOUTS.find((item) => item.name === skillName)
    return starter && { title: starter.title, description: starter.description }
}

export function inboxSetupDefaultScouts(
    configs: SignalScoutConfigApi[],
    sources: InboxSetupSource[],
    hasEvents: boolean,
    statuses: Partial<Record<AgentRosterSource, SourceProductStatus>> = {}
): ScoutSuggestionItemApi[] {
    return STARTER_SCOUTS.flatMap((starter) => {
        const config = configs.find(
            (item) =>
                item.skill_name === starter.name &&
                item.scout_origin === 'canonical' &&
                !item.enabled &&
                !item.deprecation &&
                !item.lifecycle_locked
        )
        const hasData =
            starter.source === 'general'
                ? true
                : starter.source === 'analytics'
                  ? hasEvents
                  : starter.source === 'session_replay'
                    ? statuses.replay_vision?.enabled === true
                    : sources.some(
                          (source) =>
                              source.definition.source === starter.source &&
                              (source.available ||
                                  (starter.source !== 'replay_vision' &&
                                      statuses[starter.source]?.enabled === true &&
                                      statuses[starter.source]?.enablement != null))
                      )
        if (!config || !hasData) {
            return []
        }
        return [
            {
                id: `builtin:${config.id}`,
                kind: 'canonical' as const,
                skill_name: config.skill_name,
                title: starter.title,
                why_here: starter.description,
                description: '',
                draft_body: '',
                proposed_config: {
                    run_interval_minutes: config.run_interval_minutes ?? 1440,
                    run_cron_schedule: config.run_cron_schedule,
                    emit: true,
                },
                gap: true,
                confidence: 'medium' as const,
            },
        ]
    })
}

const MAX_SETUP_SCOUTS = 5

export interface InboxSetupScoutLimit {
    limit: number
    reason: string
}

// The trial counts every enabled scout except an operational one, which is seeded for every project.
export function inboxSetupScoutLimit(
    trial: SelfDrivingTrialStatusApi | null,
    configs: Pick<SignalScoutConfigApi, 'enabled' | 'scout_role' | 'skill_name'>[],
    draft: Pick<InboxOnboardingDraftApi, 'suggestions' | 'activation_scouts'>
): InboxSetupScoutLimit {
    const fallback = { limit: MAX_SETUP_SCOUTS, reason: 'Select up to five scouts' }
    if (!trial?.enabled || (trial.grant_status !== 'active' && !trial.eligible)) {
        return fallback
    }
    const managed = new Set([...draft.suggestions.map((item) => item.skill_name), ...(draft.activation_scouts ?? [])])
    const alreadyOn = configs.filter(
        (config) => config.enabled && config.scout_role !== 'operational' && !managed.has(config.skill_name)
    ).length
    const limit = Math.max(0, trial.scout_limit - alreadyOn)
    if (limit >= MAX_SETUP_SCOUTS) {
        return fallback
    }
    return {
        limit,
        reason: alreadyOn
            ? `The free trial includes ${trial.scout_limit} scouts, and ${alreadyOn} ${alreadyOn === 1 ? 'is' : 'are'} already on`
            : `The free trial includes ${trial.scout_limit} scouts`,
    }
}

export function inboxSetupScoutChoices(
    suggestions: ScoutSuggestionItemApi[],
    selected: ScoutSuggestionItemApi[]
): ScoutSuggestionItemApi[] {
    const choices = suggestions.map(
        (suggestion) =>
            selected.find(
                (item) =>
                    item.id === suggestion.id ||
                    (item.kind === 'canonical' &&
                        suggestion.kind === 'canonical' &&
                        item.skill_name === suggestion.skill_name)
            ) ?? suggestion
    )
    return [...choices, ...selected.filter((item) => !choices.some((choice) => choice.id === item.id))]
}
