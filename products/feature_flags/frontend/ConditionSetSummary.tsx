import { FeatureFlagGroupType } from '~/types'

import { rolloutOf } from './releaseConditionsDiff'

export interface ConditionSetSummaryProps {
    group: FeatureFlagGroupType
    aggregationTargetName: string
    /** The editor phrases the criteria line as an edit in progress instead of a finished state. */
    readOnly?: boolean
}

/**
 * One line summary of who a condition set matches. For a set without criteria, the rollout
 * percentage decides the wording.
 */
export function ConditionSetSummary({
    group,
    aggregationTargetName,
    readOnly = true,
}: ConditionSetSummaryProps): JSX.Element {
    if (group.properties?.length) {
        return readOnly ? (
            <>
                Match <b>{aggregationTargetName}</b> against <b>all</b> criteria
            </>
        ) : (
            <>
                Matching <b>{aggregationTargetName}</b> against the criteria
            </>
        )
    }

    const rollout = rolloutOf(group)

    if (rollout === 100) {
        return (
            <>
                Condition set will match <b>all {aggregationTargetName}</b>
            </>
        )
    }

    if (rollout === 0) {
        return (
            <>
                Condition set will match <b>no {aggregationTargetName}</b>
            </>
        )
    }

    return (
        <>
            Condition set will match{' '}
            <b>
                <span className="tabular-nums">{rollout}%</span> of all {aggregationTargetName}
            </b>
        </>
    )
}
