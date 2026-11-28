import { useValues } from 'kea'
import { useState } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionScannersPartialUpdate } from '../generated/api'
import { refreshVisionQuota } from '../logics/visionQuotaLogic'
import { saveScannerEnabled } from './saveScannerEnabled'

export interface ScannerSave {
    turnOn: () => Promise<void>
    turnOffFreeOnly: () => Promise<void>
    saving: boolean
}

export function useScannerSave(scannerId: string, onSaved: () => void): ScannerSave {
    const { currentTeamId } = useValues(teamLogic)
    const [saving, setSaving] = useState(false)

    const run = async (save: (teamId: string) => Promise<unknown>, failure: string): Promise<void> => {
        if (!currentTeamId) {
            return
        }
        setSaving(true)
        try {
            if (await save(String(currentTeamId))) {
                refreshVisionQuota()
                onSaved()
            }
        } catch (error: any) {
            lemonToast.error(`${failure}${error?.detail ? `: ${error.detail}` : ''}. Try again from its settings.`)
        } finally {
            setSaving(false)
        }
    }

    return {
        turnOn: () => run((teamId) => saveScannerEnabled(teamId, scannerId, true), "Couldn't turn on the scanner"),
        turnOffFreeOnly: () =>
            run(
                (teamId) => visionScannersPartialUpdate(teamId, scannerId, { free_only: false }),
                "Couldn't turn off free credits only"
            ),
        saving,
    }
}
