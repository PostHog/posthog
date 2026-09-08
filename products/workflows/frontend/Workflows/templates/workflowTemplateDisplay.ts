import type { HogFlowAction, HogFlowEdge, HogFlowTemplate } from '../hogflows/types'

const TRIGGER_LABELS: Record<string, string> = {
    event: 'Starts on an event',
    'internal-event': 'Starts on an event',
    webhook: 'Starts on a webhook',
    manual: 'Starts manually',
    schedule: 'Starts on a schedule',
    tracking_pixel: 'Starts on a tracking pixel',
    batch: 'Starts for an audience',
    'data-warehouse-table': 'Starts on warehouse data',
    'data-warehouse-view': 'Starts on warehouse data',
}

const SCOPE_LABELS: Record<string, string> = {
    organization: 'Organization',
    team: 'Team',
}

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

export interface TemplateTrigger {
    type: string
    label: string
}

export function getTemplateTrigger(template: Pick<HogFlowTemplate, 'trigger' | 'actions'>): TemplateTrigger | null {
    const triggerAction = template.actions?.find((action): action is TriggerAction => action.type === 'trigger')
    const type = triggerAction?.config.type ?? template.trigger?.type
    if (!type) {
        return null
    }
    return { type, label: TRIGGER_LABELS[type] ?? 'Starts on a trigger' }
}

// Global templates are the majority, so only the narrower scopes are worth a label.
export function getTemplateScopeLabel(scope: HogFlowTemplate['scope']): string | null {
    return scope ? (SCOPE_LABELS[scope] ?? null) : null
}

// Hog function templates for the steps that hand work to an AI agent.
const AI_STEP_TEMPLATE_IDS = new Set(['template-posthog-create-task', 'template-posthog-run-scout'])

const AI_TAG = 'ai'

/**
 * A template counts as AI if it runs an AI step, or if an author tagged it `ai`. The tag covers
 * templates that reach an agent another way, such as a webhook to a service the team runs.
 */
export function isAiTemplate(template: Pick<HogFlowTemplate, 'actions' | 'tags'>): boolean {
    if (template.tags?.some((tag) => tag.toLowerCase() === AI_TAG)) {
        return true
    }
    return (template.actions ?? []).some(
        (action) => 'template_id' in action.config && AI_STEP_TEMPLATE_IDS.has(action.config.template_id)
    )
}

// A branch edge is the path a met condition takes, so it says more than the default `continue` edge.
function compareEdges(a: HogFlowEdge, b: HogFlowEdge): number {
    if (a.type !== b.type) {
        return a.type === 'branch' ? -1 : 1
    }
    return (a.index ?? 0) - (b.index ?? 0)
}

/**
 * Orders actions the way the canvas reads, top to bottom, by walking `edges` from the trigger.
 * The stored `actions` array is creation order, which is a different sequence for most templates.
 */
export function getOrderedActions(actions: HogFlowAction[], edges: HogFlowEdge[] | undefined): HogFlowAction[] {
    const trigger = actions.find((action) => action.type === 'trigger')
    if (!trigger) {
        return actions
    }

    const actionsById = new Map(actions.map((action) => [action.id, action]))
    const edgesByFrom = new Map<string, HogFlowEdge[]>()
    for (const edge of edges ?? []) {
        const fromEdges = edgesByFrom.get(edge.from) ?? []
        fromEdges.push(edge)
        edgesByFrom.set(edge.from, fromEdges)
    }
    for (const fromEdges of edgesByFrom.values()) {
        fromEdges.sort(compareEdges)
    }

    const ordered: HogFlowAction[] = []
    const visited = new Set<string>([trigger.id])
    const queue: string[] = [trigger.id]
    // A cursor rather than `shift()`, so a template with many edges stays linear.
    for (let cursor = 0; cursor < queue.length; cursor++) {
        const id = queue[cursor]
        const action = actionsById.get(id)
        if (action) {
            ordered.push(action)
        }
        for (const edge of edgesByFrom.get(id) ?? []) {
            if (!visited.has(edge.to)) {
                visited.add(edge.to)
                queue.push(edge.to)
            }
        }
    }

    // Keep any action the edges never reach, so a broken graph hides nothing
    return [...ordered, ...actions.filter((action) => !visited.has(action.id))]
}
