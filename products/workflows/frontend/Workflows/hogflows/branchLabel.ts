import type { HogFlow, HogFlowAction } from './types'

export const getBranchLabel = (action: HogFlowAction | undefined, edge: HogFlow['edges'][0]): string => {
    if (!action) {
        return `If condition #${(edge.index || 0) + 1} matches`
    }

    switch (action.type) {
        case 'wait_until_condition': {
            const waitAction = action as Extract<HogFlowAction, { type: 'wait_until_condition' }>
            const customName = waitAction.config.condition?.name
            return customName || 'If condition matches'
        }
        case 'random_cohort_branch': {
            const cohortAction = action as Extract<HogFlowAction, { type: 'random_cohort_branch' }>
            const cohort = cohortAction.config.cohorts?.[edge.index || 0]
            return cohort?.name || `If cohort #${(edge.index || 0) + 1} matches`
        }
        case 'conditional_branch': {
            const branchAction = action as Extract<HogFlowAction, { type: 'conditional_branch' }>
            const condition = branchAction.config.conditions?.[edge.index || 0]
            return condition?.name || `If condition #${(edge.index || 0) + 1} matches`
        }
        default:
            return `If condition #${(edge.index || 0) + 1} matches`
    }
}
