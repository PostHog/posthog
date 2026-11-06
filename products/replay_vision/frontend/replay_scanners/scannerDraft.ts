import { ScannerCreationMethodEnumApi } from '../generated/api.schemas'
import { ScannerFormValues } from './types'

const DRAFT_STORAGE_KEY = 'replay-vision.new-scanner-draft'
const DRAFT_VERSION = 1
const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

interface StoredScannerDraft {
    version: number
    teamId: number
    savedAt: number
    scanner: ScannerFormValues
    // The experiment the wizard was entered from. Optional, so drafts saved without it still read.
    linkedExperimentId?: number | null
    provenance?: ScannerDraftProvenance
}

/** How the form was built, so a resumed draft still reports its creation path and its AI-drafted baseline. */
export interface ScannerDraftProvenance {
    creationMethod: ScannerCreationMethodEnumApi
    goalDraftBaseline: ScannerFormValues | null
}

export interface ScannerDraft {
    scanner: ScannerFormValues
    savedAt: number
    linkedExperimentId: number | null
    provenance: ScannerDraftProvenance | null
}

function readProvenance(value: unknown): ScannerDraftProvenance | null {
    if (!value || typeof value !== 'object') {
        return null
    }
    const { creationMethod, goalDraftBaseline } = value as Partial<ScannerDraftProvenance>
    if (!Object.values(ScannerCreationMethodEnumApi).includes(creationMethod as ScannerCreationMethodEnumApi)) {
        return null
    }
    return {
        creationMethod: creationMethod as ScannerCreationMethodEnumApi,
        goalDraftBaseline: goalDraftBaseline && typeof goalDraftBaseline === 'object' ? goalDraftBaseline : null,
    }
}

export function writeScannerDraft(
    teamId: number,
    scanner: ScannerFormValues,
    linkedExperimentId: number | null = null,
    provenance: ScannerDraftProvenance | null = null
): number | null {
    const savedAt = Date.now()
    const draft: StoredScannerDraft = {
        version: DRAFT_VERSION,
        teamId,
        savedAt,
        scanner,
        linkedExperimentId,
        ...(provenance ? { provenance } : {}),
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
        return {
            scanner: draft.scanner,
            savedAt: draft.savedAt,
            linkedExperimentId: typeof draft.linkedExperimentId === 'number' ? draft.linkedExperimentId : null,
            provenance: readProvenance(draft.provenance),
        }
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
