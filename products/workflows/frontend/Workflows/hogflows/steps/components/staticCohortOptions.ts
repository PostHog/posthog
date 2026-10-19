import { LemonInputSelectOption } from '@posthog/lemon-ui'

import { CohortType } from '~/types'

type CohortOptionSource = Pick<CohortType, 'deleted' | 'id' | 'is_static' | 'name'>

export function staticCohortOptions(cohorts: CohortOptionSource[]): LemonInputSelectOption<number>[] {
    return cohorts
        .filter(
            (cohort): cohort is CohortOptionSource & { id: number } =>
                cohort.is_static === true && !cohort.deleted && typeof cohort.id === 'number'
        )
        .map((cohort) => ({
            key: String(cohort.id),
            value: cohort.id,
            label: cohort.name || `Cohort ${cohort.id}`,
        }))
        .sort((a, b) => a.label.localeCompare(b.label))
}
