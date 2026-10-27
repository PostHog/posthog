import type { ReplayObservationApi } from '../generated/api.schemas'
import { scannerLabel } from '../utils/observation'
import { watchCardHeadline } from './components/WatchFeedCard'
import { ScannerType } from './types'

export interface WatchPickSummary {
    title: string
    scannerName: string
    scannerType: ScannerType | undefined
    person: string
}

export function watchPickSummary(observation: ReplayObservationApi): WatchPickSummary {
    const scannerName = scannerLabel(observation)
    return {
        title: watchCardHeadline(observation)?.title ?? scannerName,
        scannerName,
        scannerType: observation.scanner_snapshot?.scanner_type as ScannerType | undefined,
        person: observation.recording_subject_email || observation.distinct_id || 'Anonymous',
    }
}
