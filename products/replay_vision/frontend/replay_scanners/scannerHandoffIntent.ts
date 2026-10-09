import type { ScannerFormValues } from './types'

const SCANNER_HANDOFF_INTENT_KEY = 'replay-vision.scanner-handoff-intent'
// Bump when the payload shape changes, so an entry written by an older tab is dropped instead of applied.
const SCANNER_HANDOFF_INTENT_VERSION = 1

/** One-shot hand-off of a prefilled scanner from another product's entry point (for example
 * "scan this error's recordings" in error tracking) to the creation wizard. The prefill can carry
 * customer text, such as an exception message inside the scanner name and prompt, so it travels
 * via sessionStorage rather than the URL, keeping it out of autocapture's $current_url, our own
 * replay of our app, and browser history. */
export interface ScannerHandoffIntent {
    /** Entry point that armed the hand-off, recorded on the creation-started event. */
    source: string
    scanner: Partial<ScannerFormValues>
}

export function markScannerHandoffIntent(intent: ScannerHandoffIntent): void {
    try {
        sessionStorage.setItem(
            SCANNER_HANDOFF_INTENT_KEY,
            JSON.stringify({ version: SCANNER_HANDOFF_INTENT_VERSION, ...intent })
        )
    } catch {
        // Storage can be unavailable (private mode); the entry point then just opens the wizard blank.
    }
}

/** Reads and clears the hand-off. The wizard must call this on every entry, whichever prefill
 * path wins, so a hand-off can never stay armed for the rest of the tab session and prefill a
 * later, unrelated wizard visit. */
export function consumeScannerHandoffIntent(): ScannerHandoffIntent | null {
    try {
        const raw = sessionStorage.getItem(SCANNER_HANDOFF_INTENT_KEY)
        sessionStorage.removeItem(SCANNER_HANDOFF_INTENT_KEY)
        if (!raw) {
            return null
        }
        const parsed = JSON.parse(raw)
        if (
            parsed?.version !== SCANNER_HANDOFF_INTENT_VERSION ||
            typeof parsed.source !== 'string' ||
            typeof parsed.scanner !== 'object' ||
            parsed.scanner === null
        ) {
            return null
        }
        return { source: parsed.source, scanner: parsed.scanner }
    } catch {
        return null
    }
}

const SCANNER_GOAL_DRAFT_INTENT_KEY = 'replay-vision.scanner-goal-draft-intent'
const SCANNER_GOAL_DRAFT_INTENT_TTL_MS = 60_000

/** One-shot "draft this goal now" from an in-app click, kept out of the URL so a link cannot
 * start a draft on its own. Returns false when storage is unavailable. */
export function markScannerGoalDraftIntent(goal: string): boolean {
    try {
        sessionStorage.setItem(SCANNER_GOAL_DRAFT_INTENT_KEY, JSON.stringify({ goal, at: Date.now() }))
        return true
    } catch {
        return false
    }
}

export function consumeScannerGoalDraftIntent(): string | null {
    try {
        const raw = sessionStorage.getItem(SCANNER_GOAL_DRAFT_INTENT_KEY)
        sessionStorage.removeItem(SCANNER_GOAL_DRAFT_INTENT_KEY)
        if (!raw) {
            return null
        }
        const parsed = JSON.parse(raw)
        if (typeof parsed?.goal !== 'string' || typeof parsed.at !== 'number') {
            return null
        }
        if (Date.now() - parsed.at > SCANNER_GOAL_DRAFT_INTENT_TTL_MS) {
            return null
        }
        return parsed.goal.trim() || null
    } catch {
        return null
    }
}
