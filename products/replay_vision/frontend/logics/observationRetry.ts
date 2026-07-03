import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionObservationsRetryCreate } from '../generated/api'
import { refreshVisionQuota } from './visionQuotaLogic'

/** Shared core of the retry surfaces — request, toasts, quota refresh; each caller owns its own follow-up. */
export async function requestObservationRetry(
    observationId: string,
    successMessage = 'Retrying scan — the new observation will appear shortly.'
): Promise<boolean> {
    const teamId = teamLogic.values.currentTeamId
    if (!teamId) {
        return false
    }
    try {
        await visionObservationsRetryCreate(String(teamId), observationId)
        lemonToast.success(successMessage)
        refreshVisionQuota()
        return true
    } catch (error: any) {
        lemonToast.error(`Failed to retry observation${error.detail ? `: ${error.detail}` : ''}`)
        return false
    }
}
