import { AnyPropertyFilter, PropertyFilterType } from '~/types'

import { RealtimeCohortStatusApi } from 'products/workflows/frontend/generated/api.schemas'

/** How often an open send screen refreshes a realtime cohort's status until the cohort is ready. */
export const REALTIME_COHORT_STATUS_POLL_MS = 10000

/** Whether the audience's realtime cohort can still change state, so a send screen keeps checking it. */
export function isRealtimeCohortUnresolved(status: RealtimeCohortStatusApi | null | undefined): boolean {
    return !!status && status.state !== 'ready'
}

/** The audience reduced to its realtime cohort, which has to be the only condition. */
export function keepOnlyRealtimeCohort(properties: AnyPropertyFilter[], cohortId: number): AnyPropertyFilter[] {
    return properties
        .filter((property) => property.type === PropertyFilterType.Cohort && Number(property.value) === cohortId)
        .slice(0, 1)
}

/** Whether the audience's realtime cohort is still calculating, so a send waits for it. */
export function isRealtimeCohortCalculating(status: RealtimeCohortStatusApi | null | undefined): boolean {
    return status?.state === 'building' || status?.state === 'rebuilding'
}

/** Why a send can't start, when the audience's realtime cohort can't finish calculating. */
export function realtimeCohortSendBlockedReason(
    status: RealtimeCohortStatusApi | null | undefined
): string | undefined {
    return status?.state === 'needs_attention'
        ? `Cohort '${status.name}' has a problem calculating. Open the cohort to check it.`
        : undefined
}
