import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { cohortsModel } from '~/models/cohortsModel'
import { CyclotronJobInputType } from '~/types'

import { staticCohortOptions } from './staticCohortOptions'

export function AddPersonToStaticCohortConfiguration({
    inputs,
    setInputs,
    error,
}: {
    inputs: Record<string, CyclotronJobInputType>
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
    error?: string
}): JSX.Element {
    const { allCohorts, allCohortsLoading } = useValues(cohortsModel)
    const options = useMemo(() => staticCohortOptions(allCohorts.results), [allCohorts.results])
    const value = typeof inputs.cohort_id?.value === 'number' ? inputs.cohort_id.value : null

    return (
        <LemonField.Pure label="Static cohort" error={error}>
            <LemonInputSelect<number>
                mode="single"
                fullWidth
                loading={allCohortsLoading}
                value={value === null ? [] : [value]}
                onChange={(cohortIds) => setInputs({ ...inputs, cohort_id: { value: cohortIds[0] ?? null } })}
                options={options}
                placeholder="Choose a static cohort"
                data-attr="workflow-static-cohort-select"
            />
        </LemonField.Pure>
    )
}
