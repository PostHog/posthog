import { FeatureFlagGroupType } from '~/types'

import { rolloutOf } from './releaseConditionsDiff'

export interface ConditionSetSummaryProps {
    group: FeatureFlagGroupType
    aggregationTargetName: string
    /** The editor phrases the criteria line as an edit in progress. */
    editing?: boolean
}

/**
 * One line summary of who a condition set matches. A set without criteria only matches everyone at
 * a full rollout, so the rollout percentage decides the wording.
 */
export function ConditionSetSummary({ group, aggregationTargetName, editing }: ConditionSetSummaryProps): JSX.Element {
    if (group.properties?.length) {
        return editing ? (
            <>
                Matching <b>{aggregationTargetName}</b> against the criteria
            </>
        ) : (
            <>
                Match <b>{aggregationTargetName}</b> against <b>all</b> criteria
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
