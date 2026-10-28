import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { IconCohort } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { sendCalendarLogic } from './sendCalendarLogic'
import { SendAudience } from './sendCalendarUtils'

export function SendCalendarAudience({ audience }: { audience: SendAudience }): JSX.Element {
    const { cohortsById } = useValues(sendCalendarLogic)

    if (audience.address) {
        return <div className="font-mono break-all">{audience.address}</div>
    }
    if (!audience.cohortIds.length && !audience.filters.length) {
        return <div>{audience.accounts ? 'All accounts' : 'Everyone'}</div>
    }
    return (
        <div className="flex flex-col gap-1" data-attr="send-calendar-audience">
            {audience.cohortIds.map((id) => {
                const cohort = cohortsById[id]
                return (
                    <div key={id} className="flex min-w-0 items-center gap-1">
                        <IconCohort className="shrink-0 text-secondary" />
                        <Link to={urls.cohort(id)} className="truncate" data-attr="send-calendar-cohort">
                            {cohort?.name || `Cohort ${id}`}
                        </Link>
                        {typeof cohort?.count === 'number' ? (
                            <span className="shrink-0 text-secondary">
                                {humanFriendlyNumber(cohort.count)} {cohort.count === 1 ? 'person' : 'people'}
                            </span>
                        ) : null}
                    </div>
                )
            })}
            {audience.filters.length ? <PropertyFiltersDisplay filters={audience.filters} compact /> : null}
            {audience.accounts ? <div className="text-secondary">One send for each matching account.</div> : null}
        </div>
    )
}
