import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { isEmailAction } from '../Workflows/hogflows/steps/types'
import type { HogFlow, HogFlowAction, HogFlowTemplate } from '../Workflows/hogflows/types'
import type { FirstRunSender } from './firstRunSenderLogic'
import { withFirstRunSender } from './withFirstRunSender'

export interface FirstRunWorkflowInput {
    template: HogFlowTemplate
    matchedEvent: string | null
    edits: Record<string, EmailTemplate>
    sender: Pick<FirstRunSender, 'id'> | null
    enabled: boolean
}

function withEdits(actions: HogFlowAction[], edits: Record<string, EmailTemplate>): HogFlowAction[] {
    return actions.map((action) =>
        isEmailAction(action) && edits[action.id]
            ? {
                  ...action,
                  config: {
                      ...action.config,
                      inputs: {
                          ...action.config.inputs,
                          email: { ...action.config.inputs.email, value: edits[action.id] },
                      },
                  },
              }
            : action
    )
}

function triggerEvent(filters: Record<string, any> | undefined): string | undefined {
    return filters?.events?.[0]?.id
}

function withMatchedEvent(actions: HogFlowAction[], matchedEvent: string | null): HogFlowAction[] {
    return actions.map((action) => {
        if (action.type !== 'trigger' || action.config.type !== 'event' || !matchedEvent) {
            return action
        }
        const filters = action.config.filters ?? {}
        if (triggerEvent(filters) === matchedEvent) {
            return action
        }
        const [first, ...rest] = filters.events ?? []
        return {
            ...action,
            config: {
                ...action.config,
                filters: {
                    ...filters,
                    events: [{ ...first, id: matchedEvent, name: matchedEvent, type: 'events', order: 0 }, ...rest],
                },
            },
        }
    })
}

export function buildFirstRunWorkflow({
    template,
    matchedEvent,
    edits,
    sender,
    enabled,
}: FirstRunWorkflowInput): Partial<HogFlow> {
    const { id, team_id, created_at, updated_at, created_by, image_url, tags, scope, ...content } = template
    const editedActions = withMatchedEvent(withEdits(template.actions, edits), matchedEvent)
    return {
        ...content,
        actions: sender ? withFirstRunSender(editedActions, sender) : editedActions,
        status: enabled ? 'active' : 'draft',
        version: 1,
    }
}
