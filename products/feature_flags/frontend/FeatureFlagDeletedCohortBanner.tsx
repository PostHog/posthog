import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter, humanList } from 'lib/utils/strings'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

/** Warns that release conditions target a cohort the flag evaluator cannot load, so the flag fails to evaluate. */
export function FeatureFlagDeletedCohortBanner(): JSX.Element | null {
    const { featureFlag, deletedCohortFilters } = useValues(featureFlagLogic)
    const { editFeatureFlag } = useActions(featureFlagLogic)

    if (!featureFlag.id || deletedCohortFilters.length === 0) {
        return null
    }

    const cohorts = deletedCohortFilters.map((property) =>
        property.cohort_name ? `'${property.cohort_name}'` : `ID ${property.value}`
    )
    const single = cohorts.length === 1
    const them = single ? 'it' : 'them'
    const theCohorts = single ? 'the cohort' : 'the cohorts'
    const deleted = single ? `Cohort ${cohorts[0]} was deleted.` : `Cohorts ${humanList(cohorts)} were deleted.`
    const fix = `restore ${theCohorts} or update the release conditions to remove ${them}`
    // The flag API refuses to restore, unarchive or enable a flag while a condition targets a deleted cohort.
    let consequence: string
    if (featureFlag.deleted) {
        consequence = `You can't restore the flag while it targets ${them}. Restore ${theCohorts} first.`
    } else if (featureFlag.archived) {
        consequence = `You can't unarchive the flag until you ${fix}.`
    } else if (featureFlag.active) {
        consequence = `The flag fails to evaluate for anyone who reaches a release condition that targets ${them}. ${capitalizeFirstLetter(fix)}.`
    } else {
        consequence = `You can't enable the flag until you ${fix}.`
    }

    return (
        <LemonBanner type="warning">
            <div className="flex flex-col gap-1">
                <strong>{single ? 'This flag targets a deleted cohort' : 'This flag targets deleted cohorts'}</strong>
                <span>{`${deleted} ${consequence}`}</span>
                {featureFlag.can_edit && !featureFlag.deleted && (
                    <div className="flex flex-wrap gap-2 mt-1">
                        <LemonButton
                            type="secondary"
                            size="small"
                            data-attr="feature-flag-deleted-cohort-banner-edit"
                            onClick={() => {
                                posthog.capture('feature flag deleted cohort banner edit clicked')
                                editFeatureFlag(true)
                            }}
                        >
                            Edit release conditions
                        </LemonButton>
                    </div>
                )}
            </div>
        </LemonBanner>
    )
}
