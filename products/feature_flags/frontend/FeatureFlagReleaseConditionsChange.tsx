import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { featureFlagReleaseConditionsLogic } from 'scenes/feature-flags/featureFlagReleaseConditionsLogic'

import { FeatureFlagFilters } from '~/types'

import { FeatureFlagConditionSetCard } from './FeatureFlagConditionSetCard'
import { ConditionSetChange, changedAspects, diffReleaseConditionSets, rolloutOf } from './releaseConditionsDiff'

export interface FeatureFlagReleaseConditionsChangeProps {
    flagId: string
    activityId: string
    before?: FeatureFlagFilters | null
    after: FeatureFlagFilters
}

function statusTag(set: ConditionSetChange): JSX.Element | undefined {
    if (set.status === 'added') {
        return (
            <LemonTag type="success" size="small">
                Added
            </LemonTag>
        )
    }
    if (set.status === 'changed') {
        return (
            <LemonTag type="warning" size="small">
                Changed
            </LemonTag>
        )
    }
    return undefined
}

export function FeatureFlagReleaseConditionsChange({
    flagId,
    activityId,
    before,
    after,
}: FeatureFlagReleaseConditionsChangeProps): JSX.Element {
    // The logic is keyed by id, and every history entry for one flag carries different filters,
    // so each entry needs its own key or they would all share one state.
    const logic = featureFlagReleaseConditionsLogic({
        id: `${flagId}-activity-${activityId}`,
        readOnly: true,
        filters: after,
    })
    const { aggregationTargetName, getDistinctIdName, getFlagKey } = useValues(logic)
    const diff = diffReleaseConditionSets(before, after)

    return (
        <div className="flex flex-col gap-2 py-2">
            <p className="text-xs text-muted mb-0">
                Release conditions after this change. Condition sets are evaluated top to bottom, the first match wins.
            </p>

            {diff.sets.length === 0 && (
                <p className="text-sm text-muted mb-0">No condition sets. The flag matches no one.</p>
            )}

            {diff.sets.map((set) => (
                <div key={set.index}>
                    {set.index > 0 && (
                        <div className="condition-set-separator my-2 py-0 text-center text-xs font-semibold text-muted">
                            OR
                        </div>
                    )}
                    <FeatureFlagConditionSetCard
                        group={set.group}
                        index={set.index}
                        aggregationTargetName={aggregationTargetName(set.group.aggregation_group_type_index)}
                        getDistinctIdName={getDistinctIdName}
                        getFlagKey={getFlagKey}
                        tag={statusTag(set)}
                        previousRolloutPercentage={
                            set.previous && changedAspects(set).includes('rollout')
                                ? rolloutOf(set.previous)
                                : undefined
                        }
                    />
                </div>
            ))}

            {diff.removed.length > 0 && (
                <>
                    <div className="mt-2 text-xs font-semibold text-muted">Removed by this change</div>
                    {diff.removed.map(({ group, index }) => (
                        <div key={index} className="opacity-60">
                            <FeatureFlagConditionSetCard
                                group={group}
                                index={index}
                                aggregationTargetName={aggregationTargetName(group.aggregation_group_type_index)}
                                getDistinctIdName={getDistinctIdName}
                                getFlagKey={getFlagKey}
                                tag={
                                    <LemonTag type="danger" size="small">
                                        Removed
                                    </LemonTag>
                                }
                            />
                        </div>
                    ))}
                </>
            )}
        </div>
    )
}
