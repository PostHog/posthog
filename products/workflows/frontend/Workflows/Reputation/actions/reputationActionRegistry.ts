import { bimiFindingAction } from './bimiFindingAction'
import type { RegisteredReputationAction } from './defineReputationAction'
import { dnsFindingAction } from './dnsFindingAction'
import { otherFindingAction } from './otherFindingAction'
import { pausedWorkflowAction } from './pausedWorkflowAction'
import { projectRateAction } from './projectRateAction'
import { projectSuspendedAction } from './projectSuspendedAction'
import { providerRateAction } from './providerRateAction'
import { providerStatusAction } from './providerStatusAction'
import { rateFindingAction } from './rateFindingAction'
import type { ReputationActionContext } from './reputationActionContext'
import { compareReputationActionRanks } from './reputationActionRanking'
import type { ReputationAction, ReputationActionKind } from './reputationActionTypes'
import { workflowRateAction } from './workflowRateAction'

/**
 * Every item the action list can show, keyed by its kind. To add one, write a `defineReputationAction`
 * file and list it here. Rows sort by their rank, so this order only settles exact ties.
 */
export const REPUTATION_ACTIONS: Readonly<Record<ReputationActionKind, RegisteredReputationAction>> = {
    'project-suspended': projectSuspendedAction,
    'provider-status': providerStatusAction,
    'paused-workflow': pausedWorkflowAction,
    'rate-finding': rateFindingAction,
    'dns-finding': dnsFindingAction,
    'bimi-finding': bimiFindingAction,
    'other-finding': otherFindingAction,
    'project-rate': projectRateAction,
    'workflow-rate': workflowRateAction,
    'provider-rate': providerRateAction,
}

export function buildReputationActions(context: ReputationActionContext): ReputationAction[] {
    const seenKeys = new Map<string, number>()
    return Object.values(REPUTATION_ACTIONS)
        .flatMap((action) => action.build(context))
        .map((row) => {
            // A tenant can hold two findings of one type, for example DKIM on two domains.
            const seen = seenKeys.get(row.key) ?? 0
            seenKeys.set(row.key, seen + 1)
            return seen > 0 ? { ...row, key: `${row.key}:${seen + 1}` } : row
        })
        .sort((a, b) => compareReputationActionRanks(a.rank, b.rank))
        .map(({ rank, ...row }) => row)
}
