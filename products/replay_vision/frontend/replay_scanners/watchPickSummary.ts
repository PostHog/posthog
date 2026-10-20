import type { ReplayObservationApi } from '../generated/api.schemas'
import { watchCardHeadline } from './components/WatchFeedCard'
import { ScannerType } from './types'

export interface WatchPickSummary {
    title: string
    scannerName: string
    scannerType: ScannerType | undefined
    person: string
}

export function watchPickSummary(observation: ReplayObservationApi): WatchPickSummary {
    const scannerName = (observation.scanner_snapshot?.name as string | undefined) || '(untitled scanner)'
    return {
        title: watchCardHeadline(observation)?.title ?? scannerName,
        scannerName,
        scannerType: observation.scanner_snapshot?.scanner_type as ScannerType | undefined,
        person: observation.recording_subject_email || observation.distinct_id || 'Anonymous',
    }
}
