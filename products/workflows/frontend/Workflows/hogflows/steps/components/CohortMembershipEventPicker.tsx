import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { cohortsModel } from '~/models/cohortsModel'

import { CohortMembershipEventValue } from './cohortMembershipEvent'

export interface CohortMembershipEventPickerProps {
    value: CohortMembershipEventValue | null
    onChange: (value: CohortMembershipEventValue | null) => void
    dataAttr: string
}

export function CohortMembershipEventPicker({
    value,
    onChange,
    dataAttr,
}: CohortMembershipEventPickerProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { loadCohortsByIds } = useActions(cohortsModel)

    const cohortId = value?.cohortId
    useEffect(() => {
        if (cohortId) {
            loadCohortsByIds({ ids: [cohortId] })
        }
    }, [cohortId, loadCohortsByIds])

    return (
        <div className="flex flex-wrap gap-2 items-center">
            <TaxonomicPopover
                groupType={TaxonomicFilterGroupType.Cohorts}
                value={cohortId}
                onChange={(nextCohortId) =>
                    onChange(
                        nextCohortId
                            ? { cohortId: Number(nextCohortId), transition: value?.transition ?? 'entered' }
                            : null
                    )
                }
                renderValue={(id) => <>{cohortsById[id]?.name ?? `Cohort ${id}`}</>}
                placeholder="Choose a cohort"
                allowClear
                data-attr={`${dataAttr}-cohort`}
            />
            {value ? (
                <LemonSegmentedButton
                    size="small"
                    value={value.transition}
                    onChange={(transition) => onChange({ ...value, transition })}
                    options={[
                        { value: 'entered', label: 'Joins the cohort', 'data-attr': `${dataAttr}-joins` },
                        { value: 'left', label: 'Leaves the cohort', 'data-attr': `${dataAttr}-leaves` },
                    ]}
                />
            ) : null}
        </div>
    )
}
