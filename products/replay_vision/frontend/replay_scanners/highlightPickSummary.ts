import type { ReplayObservationApi } from '../generated/api.schemas'
import { scannerLabel } from '../utils/observation'
import { highlightCardHeadline } from './components/HighlightFeedCard'
import { ScannerType } from './types'

export interface HighlightPickSummary {
    title: string
    scannerName: string
    scannerType: ScannerType | undefined
    person: string
}

export function highlightPickSummary(observation: ReplayObservationApi): HighlightPickSummary {
    const scannerName = scannerLabel(observation)
    return {
        title: highlightCardHeadline(observation)?.title ?? scannerName,
        scannerName,
        scannerType: observation.scanner_snapshot?.scanner_type as ScannerType | undefined,
        person: observation.recording_subject_email || observation.distinct_id || 'Anonymous',
    }
}
