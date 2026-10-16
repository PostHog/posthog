import { RealtimeCohortStatusApi } from 'products/workflows/frontend/generated/api.schemas'

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
