import { ScannerFormValues } from './types'

const DRAFT_STORAGE_KEY = 'replay-vision.new-scanner-draft'
const DRAFT_VERSION = 1
const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

interface StoredScannerDraft {
    version: number
    teamId: number
    savedAt: number
    scanner: ScannerFormValues
}

export interface ScannerDraft {
    scanner: ScannerFormValues
    savedAt: number
}

export function writeScannerDraft(teamId: number, scanner: ScannerFormValues): number | null {
    const savedAt = Date.now()
    const draft: StoredScannerDraft = {
        version: DRAFT_VERSION,
        teamId,
        savedAt,
        scanner,
    }
    try {
        localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft))
        return savedAt
    } catch {
        return null
    }
}

export function readScannerDraft(teamId: number): ScannerDraft | null {
    try {
        const raw = localStorage.getItem(DRAFT_STORAGE_KEY)
        if (!raw) {
            return null
        }
        const draft: StoredScannerDraft = JSON.parse(raw)
        if (
            draft.version !== DRAFT_VERSION ||
            draft.teamId !== teamId ||
            typeof draft.savedAt !== 'number' ||
            Date.now() - draft.savedAt > DRAFT_MAX_AGE_MS ||
            !draft.scanner
        ) {
            return null
        }
        return { scanner: draft.scanner, savedAt: draft.savedAt }
    } catch {
        return null
    }
}

export function clearScannerDraft(): void {
    try {
        localStorage.removeItem(DRAFT_STORAGE_KEY)
    } catch {
        // Nothing to clean up if storage is unavailable.
    }
}
