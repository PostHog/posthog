import type {
    DataSuggestionApi,
    DataSuggestionStageEnumApi,
    DataSuggestionStepKindEnumApi,
} from '../../generated/api.schemas'
import type { HogFlowTemplate } from '../../Workflows/hogflows/types'
import { WorkflowSuggestion } from './workflowSuggestionRules'

export type SuggestionStepKind = DataSuggestionStepKindEnumApi

/** One card, whether the AI wrote it or a built-in rule matched it. */
export type SuggestionCard =
    | {
          key: string
          source: 'ai'
          stage: DataSuggestionStageEnumApi
          title: string
          description: string
          triggerEvent: string
          weeklyCount: number
          steps: SuggestionStepKind[]
          suggestionId: string
      }
    | {
          key: string
          source: 'rules'
          title: string
          description: string
          triggerEvent: string
          weeklyCount: number
          steps: SuggestionStepKind[]
          suggestion: WorkflowSuggestion
      }

export function cardFromAi(suggestion: DataSuggestionApi): SuggestionCard {
    return {
        key: `ai-${suggestion.id}`,
        source: 'ai',
        stage: suggestion.stage,
        title: suggestion.name,
        description: suggestion.description,
        triggerEvent: suggestion.trigger_event,
        weeklyCount: suggestion.weekly_count,
        steps: suggestion.step_outline,
        suggestionId: suggestion.id,
    }
}

export function cardFromRules(suggestion: WorkflowSuggestion): SuggestionCard {
    return {
        key: `rules-${suggestion.rule.key}`,
        source: 'rules',
        title: suggestion.template.name,
        description: suggestion.rule.description,
        triggerEvent: suggestion.eventName,
        weeklyCount: suggestion.weeklyCount,
        steps: templateStepKinds(suggestion.template),
        suggestion,
    }
}

export function templateStepKinds(template: HogFlowTemplate): SuggestionStepKind[] {
    const kinds: SuggestionStepKind[] = []
    for (const action of template.actions) {
        if (action.type === 'function_email') {
            kinds.push('email')
        } else if (action.type === 'delay') {
            kinds.push('delay')
        } else if (action.type === 'conditional_branch') {
            kinds.push('branch')
        } else if (action.type === 'function') {
            kinds.push(action.config.template_id === 'template-slack' ? 'slack' : 'webhook')
        }
    }
    return kinds
}
