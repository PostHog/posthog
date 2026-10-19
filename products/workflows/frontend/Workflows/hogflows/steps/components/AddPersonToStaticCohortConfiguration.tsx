import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSearchableSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobInputType } from '~/types'

import { staticCohortOptions } from './staticCohortOptions'
import { staticCohortPickerLogic } from './staticCohortPickerLogic'

export function AddPersonToStaticCohortConfiguration({
    actionId,
    inputs,
    setInputs,
    error,
}: {
    actionId: string
    inputs: Record<string, CyclotronJobInputType>
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
    error?: string
}): JSX.Element {
    const value = typeof inputs.cohort_id?.value === 'number' ? inputs.cohort_id.value : null
    const logic = staticCohortPickerLogic({ id: actionId, selectedCohortId: value })
    const { cohortPageLoading, hasMoreCohorts, visibleCohorts } = useValues(logic)
    const { loadMoreCohorts, setSearchTerm } = useActions(logic)
    const options = useMemo(() => staticCohortOptions(visibleCohorts), [visibleCohorts])
    const sections = useMemo(
        () => [
            {
                options,
                footer: hasMoreCohorts ? (
                    <LemonButton
                        type="tertiary"
                        fullWidth
                        center
                        loading={cohortPageLoading}
                        onClick={loadMoreCohorts}
                        data-attr="workflow-static-cohort-load-more"
                    >
                        Load more cohorts
                    </LemonButton>
                ) : undefined,
            },
        ],
        [cohortPageLoading, hasMoreCohorts, loadMoreCohorts, options]
    )

    return (
        <LemonField.Pure label="Static cohort" error={error}>
            <LemonSearchableSelect<number | null>
                fullWidth
                allowClear
                loading={cohortPageLoading}
                value={value}
                onChange={(cohortId) => setInputs({ ...inputs, cohort_id: { value: cohortId } })}
                options={sections}
                placeholder="Choose a static cohort"
                searchPlaceholder="Search static cohorts"
                searchInputDataAttr="workflow-static-cohort-search"
                onSearchChange={setSearchTerm}
                filterOptionsLocally={false}
                menu={{ onVisibilityChange: (visible) => visible && setSearchTerm('') }}
                data-attr="workflow-static-cohort-select"
            />
        </LemonField.Pure>
    )
}
