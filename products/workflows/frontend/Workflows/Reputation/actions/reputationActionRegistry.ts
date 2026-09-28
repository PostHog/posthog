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
import { ReputationActionInputs, buildReputationActionContext } from './reputationActionContext'
import { compareReputationActionRanks } from './reputationActionRanking'
import type { ReputationAction } from './reputationActionTypes'
import { workflowRateAction } from './workflowRateAction'

/**
 * Every item the action list can show. To add one, write a `defineReputationAction` file and list
 * it here. Rows sort by their rank, so this order only settles exact ties.
 */
export const REPUTATION_ACTIONS: readonly RegisteredReputationAction[] = [
    projectSuspendedAction,
    providerStatusAction,
    pausedWorkflowAction,
    rateFindingAction,
    dnsFindingAction,
    bimiFindingAction,
    otherFindingAction,
    projectRateAction,
    workflowRateAction,
    providerRateAction,
]

/** Everything the Reputation tab knows, turned into a list of fixes, worst first. */
export function buildReputationActions(inputs: ReputationActionInputs): ReputationAction[] {
    const context = buildReputationActionContext(inputs)
    const seenKeys = new Map<string, number>()
    return REPUTATION_ACTIONS.flatMap((action) => action.build(context))
        .map((row) => {
            // A tenant can hold two findings of one type, for example DKIM on two domains.
            const seen = seenKeys.get(row.key) ?? 0
            seenKeys.set(row.key, seen + 1)
            return seen > 0 ? { ...row, key: `${row.key}:${seen + 1}` } : row
        })
        .sort((a, b) => compareReputationActionRanks(a.rank, b.rank))
        .map(({ rank, ...row }) => row)
}
