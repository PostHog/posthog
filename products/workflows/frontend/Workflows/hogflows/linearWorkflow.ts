import type { HogFlow, HogFlowAction } from './types'

export const BRANCHING_ACTION_TYPES = ['conditional_branch', 'random_cohort_branch', 'wait_until_condition'] as const

export function isBranchingAction(action: Pick<HogFlowAction, 'type'>): boolean {
    return BRANCHING_ACTION_TYPES.includes(action.type as (typeof BRANCHING_ACTION_TYPES)[number])
}

export function getLinearWorkflowActionIds(workflow: Pick<HogFlow, 'actions' | 'edges'>): string[] | null {
    const { actions, edges } = workflow
    const actionsById = new Map(actions.map((action) => [action.id, action]))
    const trigger = actions.filter((action) => action.type === 'trigger')
    const exit = actions.filter((action) => action.type === 'exit')

    if (
        trigger.length !== 1 ||
        exit.length !== 1 ||
        edges.length !== actions.length - 1 ||
        actions.some(isBranchingAction) ||
        edges.some((edge) => edge.type !== 'continue')
    ) {
        return null
    }

    const incomingById = new Map<string, number>()
    const outgoingById = new Map<string, string>()

    for (const edge of edges) {
        if (!actionsById.has(edge.from) || !actionsById.has(edge.to) || outgoingById.has(edge.from)) {
            return null
        }
        incomingById.set(edge.to, (incomingById.get(edge.to) ?? 0) + 1)
        outgoingById.set(edge.from, edge.to)
    }

    for (const action of actions) {
        const incoming = incomingById.get(action.id) ?? 0
        const outgoing = outgoingById.has(action.id)
        if (
            (action.type === 'trigger' && incoming !== 0) ||
            (action.type !== 'trigger' && incoming !== 1) ||
            (action.type === 'exit' && outgoing) ||
            (action.type !== 'exit' && !outgoing)
        ) {
            return null
        }
    }

    const actionIds: string[] = []
    let actionId: string | undefined = trigger[0].id
    while (actionId) {
        if (actionIds.includes(actionId)) {
            return null
        }
        actionIds.push(actionId)
        actionId = outgoingById.get(actionId)
    }

    return actionIds.length === actions.length && actionsById.get(actionIds.at(-1) ?? '')?.type === 'exit'
        ? actionIds
        : null
}
