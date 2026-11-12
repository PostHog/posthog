import { CADENCE_LABELS } from 'scenes/data-warehouse/saved_queries/SyncFrequencySelect'

import { DataModelingSyncInterval } from '~/types'

import type { WarehouseSuggestionMaterializePayloadApi } from './generated/api.schemas'
import { INTERVAL_SECONDS, intervalForSeconds } from './refreshIntervals'
import { shorterScheduleWarning, suggestedScheduleHint } from './suggestionCopy'

export interface MaterializeScheduleNotes {
    pickedSeconds: number
    suggestedHint: string | null
    shorterWarning: string | null
}

export function materializeScheduleNotes(
    payload: WarehouseSuggestionMaterializePayloadApi,
    pickedInterval: DataModelingSyncInterval | null,
    pickedShorterThanSuggested: boolean
): MaterializeScheduleNotes {
    const suggestedInterval = intervalForSeconds(payload.refresh_interval_seconds)
    const suggestedCadence = suggestedInterval ? CADENCE_LABELS[suggestedInterval] : null
    return {
        pickedSeconds: pickedInterval ? INTERVAL_SECONDS[pickedInterval] : payload.refresh_interval_seconds,
        suggestedHint: suggestedCadence
            ? suggestedScheduleHint(payload.refresh_interval_basis, suggestedCadence)
            : null,
        shorterWarning:
            pickedShorterThanSuggested && suggestedCadence
                ? shorterScheduleWarning(payload.refresh_interval_basis, suggestedCadence)
                : null,
    }
}
