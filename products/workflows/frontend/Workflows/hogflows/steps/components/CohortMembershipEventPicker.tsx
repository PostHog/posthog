import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { cohortsModel } from '~/models/cohortsModel'

import { CohortTypeEnumApi } from 'products/cohorts/frontend/generated/api.schemas'

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

    // The cohorts endpoint returns cohort_type, which the shared CohortType does not declare.
    const cohort = cohortId ? (cohortsById[cohortId] as { cohort_type?: string | null } | undefined) : undefined
    // Only realtime cohorts emit membership changes, so any other cohort never converts or ends a wait.
    const notRealtime = !!cohort && cohort.cohort_type !== CohortTypeEnumApi.Realtime

    return (
        <div className="flex flex-col gap-1">
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
            {notRealtime ? (
                <span className="text-xs text-danger">
                    This cohort isn't realtime, so it never reports people joining or leaving. Choose a realtime cohort.
                </span>
            ) : null}
        </div>
    )
}
