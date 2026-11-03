import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter, humanList } from 'lib/utils/strings'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { CohortPropertyFilter } from '~/types'

import { cohortCanBeRestored, restoreChecksCohorts } from './deletedCohortFilters'

function cohortName(property: CohortPropertyFilter): string {
    return property.cohort_name ? `'${property.cohort_name}'` : `ID ${property.value}`
}

function describeCohorts(names: string[], singular: string, plural: string): string[] {
    if (names.length === 0) {
        return []
    }
    return [names.length === 1 ? `Cohort ${names[0]} ${singular}.` : `Cohorts ${humanList(names)} ${plural}.`]
}

/** Warns that release conditions target a cohort the flag evaluator cannot load, so the flag fails to evaluate. */
export function FeatureFlagDeletedCohortBanner(): JSX.Element | null {
    const { featureFlag, deletedCohortFilters } = useValues(featureFlagLogic)
    const { editFeatureFlag } = useActions(featureFlagLogic)

    if (!featureFlag.id || deletedCohortFilters.length === 0) {
        return null
    }

    const deletedNames = deletedCohortFilters.filter(cohortCanBeRestored).map(cohortName)
    const missingNames = deletedCohortFilters.filter((property) => !cohortCanBeRestored(property)).map(cohortName)
    const single = deletedCohortFilters.length === 1
    const them = single ? 'it' : 'them'
    const theCohorts = single ? 'the cohort' : 'the cohorts'
    const kinds = humanList([...(deletedNames.length ? ['deleted'] : []), ...(missingNames.length ? ['missing'] : [])])
    const whatHappened = [
        ...describeCohorts(deletedNames, 'was deleted', 'were deleted'),
        ...describeCohorts(missingNames, 'does not exist in this project', 'do not exist in this project'),
    ].join(' ')
    const restorable = missingNames.length === 0
    const removeThem = `update the release conditions to remove ${them}`
    const fix = restorable ? `restore ${theCohorts} or ${removeThem}` : removeThem
    // The flag API refuses to restore, unarchive or enable a flag while a condition targets a deleted cohort.
    let consequence: string
    if (restoreChecksCohorts(featureFlag)) {
        consequence = `You can't restore the flag until you ${fix}.`
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
                <strong>{single ? `This flag targets a ${kinds} cohort` : `This flag targets ${kinds} cohorts`}</strong>
                <span>{`${whatHappened} ${consequence}`}</span>
                {featureFlag.can_edit && (
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
