import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionObservationsCancelCreate } from '../generated/api'
import { refreshVisionQuota } from './visionQuotaLogic'

/** Shared core of the cancel surfaces: request, toasts, quota refresh. Each caller owns its own follow-up. */
export async function requestObservationCancel(observationId: string): Promise<boolean> {
    const teamId = teamLogic.values.currentTeamId
    if (!teamId) {
        return false
    }
    try {
        await visionObservationsCancelCreate(String(teamId), observationId)
        lemonToast.success('Scan canceled. It uses no credits.')
        refreshVisionQuota()
        return true
    } catch (error) {
        const detail = error instanceof ApiError && error.detail ? `: ${error.detail}` : ''
        lemonToast.error(`Failed to cancel scan${detail}`)
        return false
    }
}
