import type { HogFlowTemplate } from '../../Workflows/hogflows/types'
import {
    WORKFLOW_SUGGESTION_RULES,
    WorkflowSuggestionRuleKey,
    findSuggestionCandidates,
    rankSuggestions,
    suggestionTriggerConfig,
    withoutUsedEvents,
} from './workflowSuggestionRules'

const ruleTemplate = (key: WorkflowSuggestionRuleKey, triggerEvents: string[] = []): HogFlowTemplate => {
    const rule = WORKFLOW_SUGGESTION_RULES.find((r) => r.key === key)!
    return {
        id: rule.templateId,
        name: `Template for ${key}`,
        actions: [
            {
                id: 'trigger_node',
                name: 'Trigger',
                type: 'trigger',
                config: {
                    type: 'event',
                    filters: {
                        events: triggerEvents.map((id, order) => ({ id, name: id, type: 'events', order })),
                        properties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }],
                    },
                },
            },
        ],
    } as unknown as HogFlowTemplate
}

const ALL_TEMPLATES = WORKFLOW_SUGGESTION_RULES.map((rule) => ruleTemplate(rule.key))

describe('workflowSuggestionRules', () => {
    test.each([
        ['user signed up', 'signup'],
        ['user_signed_up', 'signup'],
        ['UserSignedUp', 'signup'],
        ['signup', 'signup'],
        ['sign-up', 'signup'],
        ['account_created', 'signup'],
        ['registration_completed', 'signup'],
        ['trial_started', 'trial_started'],
        ['TrialStarted', 'trial_started'],
        ['plan_upgraded', 'upgraded'],
        ['subscription_created', 'upgraded'],
        ['$conversation_ticket_created', 'support_ticket'],
        ['survey sent', 'survey_response'],
    ])('matches %s to the %s rule', (eventName, expectedRule) => {
        const candidates = findSuggestionCandidates([eventName], ALL_TEMPLATES)
        expect(candidates.map((c) => c.rule.key)).toEqual([expectedRule])
    })

    test.each([
        ['$pageview'],
        ['signup_page_viewed'],
        ['sign_up_button_clicked'],
        ['project_created'],
        ['trial_ended'],
        ['downgraded'],
        ['survey shown'],
    ])('does not match %s', (eventName) => {
        expect(findSuggestionCandidates([eventName], ALL_TEMPLATES)).toEqual([])
    })

    it('skips a rule whose template is not available', () => {
        const templates = ALL_TEMPLATES.filter((t) => t.id !== ruleTemplate('signup').id)
        expect(findSuggestionCandidates(['user_signed_up'], templates)).toEqual([])
    })

    it('keeps the busiest event per rule, drops silent ones, and sorts by volume', () => {
        const candidates = findSuggestionCandidates(
            ['signup', 'user_signed_up', 'trial_started', '$conversation_ticket_created'],
            ALL_TEMPLATES
        )
        const ranked = rankSuggestions(candidates, {
            signup: 12,
            user_signed_up: 2140,
            $conversation_ticket_created: 318,
        })
        expect(ranked.map((s) => [s.rule.key, s.eventName, s.weeklyCount])).toEqual([
            ['signup', 'user_signed_up', 2140],
            ['support_ticket', '$conversation_ticket_created', 318],
        ])
    })

    it('drops events a workflow already uses, and rules left with none', () => {
        const candidates = findSuggestionCandidates(['signup', 'user_signed_up', 'trial_started'], ALL_TEMPLATES)
        const remaining = withoutUsedEvents(candidates, new Set(['user_signed_up', 'trial_started']))
        expect(remaining.map((c) => [c.rule.key, c.eventNames])).toEqual([['signup', ['signup']]])
    })

    it('swaps the trigger event and keeps the template filters', () => {
        const config = suggestionTriggerConfig(ruleTemplate('signup', ['user signed up']), 'user_signed_up')
        expect(config).toEqual({
            type: 'event',
            filters: {
                events: [{ id: 'user_signed_up', name: 'user_signed_up', type: 'events', order: 0 }],
                properties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }],
            },
        })
    })

    it('leaves the trigger alone when the template already uses the event', () => {
        expect(suggestionTriggerConfig(ruleTemplate('survey_response', ['survey sent']), 'survey sent')).toBeNull()
    })
})
