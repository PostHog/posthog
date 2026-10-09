import type { HogFlowTemplate } from '../../Workflows/hogflows/types'
import type { WorkflowTriggerConfig } from '../../Workflows/workflowTriggerPrefill'

// pinned: analytics property values for the `workflows data suggestion *` events - renaming breaks dashboards
export type WorkflowSuggestionRuleKey = 'signup' | 'trial_started' | 'upgraded' | 'support_ticket' | 'survey_response'

export interface WorkflowSuggestionRule {
    key: WorkflowSuggestionRuleKey
    /** Global templates keep their ids stable, see products/workflows/backend/templates/README.md. */
    templateId: string
    matches: (normalizedEventName: string) => boolean
    description: string
}

export const MAX_WORKFLOW_SUGGESTIONS = 3

export const WORKFLOW_SUGGESTION_RULES: WorkflowSuggestionRule[] = [
    {
        key: 'signup',
        templateId: '019b6f44-f9a3-0000-c4a7-b8050d25d690',
        matches: (name) =>
            /^(?:(?:user|customer|account) )?(?:signed ?up|sign ?up|registered|registration completed?)$/.test(name) ||
            /^(?:account|user) created$/.test(name),
        description: 'Greet people with an email right after they sign up.',
    },
    {
        key: 'trial_started',
        templateId: '019b6fc6-ad68-0000-2c21-f701205f3f5c',
        matches: (name) =>
            /^(?:(?:user|account) )?trial (?:started|start|began|activated)$/.test(name) || name === 'started trial',
        description: 'Nudge people to upgrade while their trial is running.',
    },
    {
        key: 'upgraded',
        templateId: '019ce206-1ef1-0000-f1c1-3f9c433294c6',
        matches: (name) =>
            /^(?:(?:user|account|plan|subscription) )?upgraded$/.test(name) ||
            /^(?:plan|subscription) (?:upgraded|created|started)$/.test(name) ||
            name === 'subscribed',
        description: 'Send a webhook to your own systems when someone upgrades.',
    },
    {
        key: 'support_ticket',
        templateId: '019ce1f1-5d12-0000-e318-4b3ebd4b2aea',
        matches: (name) => name === 'conversation ticket created',
        description: 'Post each new support ticket to Slack.',
    },
    {
        key: 'survey_response',
        templateId: '019cc379-c4c6-0000-9aee-d5efa598d0f4',
        matches: (name) => name === 'survey sent',
        description: 'Alert your team in Slack when someone leaves a low survey score.',
    },
]

/** `user_signed_up`, `UserSignedUp`, `user-signed-up` and `$user signed up` all become `user signed up`. */
export function normalizeEventName(eventName: string): string {
    return eventName
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim()
}

export interface WorkflowSuggestionCandidate {
    rule: WorkflowSuggestionRule
    template: HogFlowTemplate
    eventNames: string[]
}

export function findSuggestionCandidates(
    eventNames: string[],
    templates: HogFlowTemplate[]
): WorkflowSuggestionCandidate[] {
    const templatesById = new Map(templates.map((template) => [template.id, template]))
    const candidates: WorkflowSuggestionCandidate[] = []
    for (const rule of WORKFLOW_SUGGESTION_RULES) {
        const template = templatesById.get(rule.templateId)
        if (!template) {
            continue
        }
        const matching = eventNames.filter((eventName) => rule.matches(normalizeEventName(eventName)))
        if (matching.length > 0) {
            candidates.push({ rule, template, eventNames: matching })
        }
    }
    return candidates
}

export function withoutUsedEvents(
    candidates: WorkflowSuggestionCandidate[],
    usedEventNames: Set<string>
): WorkflowSuggestionCandidate[] {
    return candidates
        .map((candidate) => ({
            ...candidate,
            eventNames: candidate.eventNames.filter((eventName) => !usedEventNames.has(eventName)),
        }))
        .filter((candidate) => candidate.eventNames.length > 0)
}

export interface WorkflowSuggestion {
    rule: WorkflowSuggestionRule
    template: HogFlowTemplate
    eventName: string
    weeklyCount: number
}

export function rankSuggestions(
    candidates: WorkflowSuggestionCandidate[],
    weeklyCounts: Record<string, number>
): WorkflowSuggestion[] {
    const suggestions: WorkflowSuggestion[] = []
    for (const candidate of candidates) {
        let best: { eventName: string; weeklyCount: number } | null = null
        for (const eventName of candidate.eventNames) {
            const weeklyCount = weeklyCounts[eventName] ?? 0
            if (weeklyCount > 0 && (!best || weeklyCount > best.weeklyCount)) {
                best = { eventName, weeklyCount }
            }
        }
        if (best) {
            suggestions.push({ rule: candidate.rule, template: candidate.template, ...best })
        }
    }
    return suggestions.sort((a, b) => b.weeklyCount - a.weeklyCount).slice(0, MAX_WORKFLOW_SUGGESTIONS)
}

/** Null when the template already triggers on exactly this event, or has no event trigger to swap. */
export function suggestionTriggerConfig(template: HogFlowTemplate, eventName: string): WorkflowTriggerConfig | null {
    const trigger = template.actions.find((action) => action.type === 'trigger')
    if (!trigger || trigger.type !== 'trigger' || trigger.config.type !== 'event') {
        return null
    }
    const events = trigger.config.filters.events ?? []
    if (events.length === 1 && events[0]?.id === eventName) {
        return null
    }
    return {
        ...trigger.config,
        filters: {
            ...trigger.config.filters,
            events: [{ id: eventName, name: eventName, type: 'events', order: 0 }],
        },
    }
}
