import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { cohortsModel } from '~/models/cohortsModel'
import { CyclotronJobInputType } from '~/types'

export function AddToStaticCohortConfiguration({
    inputs,
    setInputs,
    error,
}: {
    inputs: Record<string, CyclotronJobInputType>
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
    error?: string
}): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { loadCohortsByIds } = useActions(cohortsModel)

    const cohortId = typeof inputs.cohort_id?.value === 'number' ? inputs.cohort_id.value : null
    const cohort = cohortId ? cohortsById[cohortId] : undefined

    useEffect(() => {
        if (cohortId) {
            loadCohortsByIds({ ids: [cohortId] })
        }
    }, [cohortId, loadCohortsByIds])

    return (
        <LemonField.Pure
            label="Static cohort"
            info="Adds the workflow run's person. Nothing changes if they're already in the cohort."
            error={error ?? (cohort && !cohort.is_static ? 'Choose a static cohort.' : undefined)}
        >
            <TaxonomicPopover
                groupType={TaxonomicFilterGroupType.Cohorts}
                value={cohortId}
                onChange={(value) => setInputs({ ...inputs, cohort_id: { value: Number(value) } })}
                renderValue={(value) => <>{cohortsById[value]?.name ?? `Cohort ${value}`}</>}
                placeholder="Choose a static cohort"
                data-attr="workflow-add-to-static-cohort-cohort"
            />
        </LemonField.Pure>
    )
}
