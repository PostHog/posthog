import { useMountedLogic, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { IconCohort, IconOpenInNew } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { AudienceCohort, broadcastAudienceCohortsLogic } from './broadcastAudienceCohortsLogic'

function CohortMembers({ cohort }: { cohort: AudienceCohort }): JSX.Element {
    if (cohort.isCalculating) {
        return (
            <span className="flex items-center gap-1 text-secondary">
                <Spinner className="text-sm" /> Matching people…
            </span>
        )
    }
    if (cohort.failed) {
        return (
            <span className="flex items-center gap-1 text-warning">
                <IconWarning /> Couldn't match the people on this list. Open the cohort to see why.
            </span>
        )
    }
    const people = `${humanFriendlyNumber(cohort.count ?? 0)} ${cohort.count === 1 ? 'person' : 'people'}`
    if (cohort.importTotal && cohort.importUnmatched) {
        return (
            <span className="text-secondary">
                {people}. {humanFriendlyNumber(cohort.importUnmatched)} of {humanFriendlyNumber(cohort.importTotal)} on
                the list aren't in PostHog and won't get this email.
            </span>
        )
    }
    return <span className="text-secondary">{people}</span>
}

/** The cohorts in a broadcast's audience, each with its size and a link to the full cohort. */
export function BroadcastAudienceCohorts(): JSX.Element | null {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const { cohortIds, audienceCohorts } = useValues(broadcastAudienceCohortsLogic(props))

    if (cohortIds.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1" data-attr="broadcast-audience-cohorts">
            {cohortIds.map((id) => {
                const cohort = audienceCohorts[id]
                return (
                    <div
                        key={id}
                        className="flex flex-wrap items-center justify-between gap-2 rounded border bg-surface-primary px-3 py-2"
                    >
                        <div className="flex min-w-0 items-center gap-2">
                            <IconCohort className="shrink-0 text-lg text-secondary" />
                            <div className="flex min-w-0 flex-col">
                                <div className="flex items-center gap-2">
                                    <span className="truncate font-semibold">{cohort?.name ?? `Cohort ${id}`}</span>
                                    {cohort ? (
                                        <LemonTag type="muted" size="small">
                                            {cohort.isStatic ? 'List' : 'Dynamic'}
                                        </LemonTag>
                                    ) : null}
                                </div>
                                <div className="text-xs">
                                    {cohort ? (
                                        <CohortMembers cohort={cohort} />
                                    ) : cohort === null ? (
                                        <span className="text-secondary">Couldn't load this cohort.</span>
                                    ) : (
                                        <Spinner className="text-sm" />
                                    )}
                                </div>
                            </div>
                        </div>
                        <LemonButton
                            size="small"
                            type="secondary"
                            to={urls.cohort(id)}
                            targetBlank
                            sideIcon={<IconOpenInNew />}
                            data-attr="broadcast-audience-open-cohort"
                        >
                            Open cohort
                        </LemonButton>
                    </div>
                )
            })}
        </div>
    )
}
