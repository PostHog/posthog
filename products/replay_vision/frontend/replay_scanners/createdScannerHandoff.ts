import type { ScannerFormValues } from './types'

/** One-shot hand-off of a just-created scanner from the wizard to its detail scene. The wizard
 * already holds the created scanner in the create response, so the detail scene can render at once
 * instead of waiting on a GET that can stall on read-after-write. A module variable is enough: the
 * hand-off happens within one SPA navigation, and a reload clears it so the GET takes over. */
let handedOff: { id: string; scanner: ScannerFormValues } | null = null

export function handOffCreatedScanner(id: string, scanner: ScannerFormValues): void {
    handedOff = { id, scanner }
}

/** Reads and clears the hand-off, but only for a matching scanner id, so a stale hand-off can never
 * seed the wrong detail page. */
export function consumeCreatedScanner(id: string): ScannerFormValues | null {
    if (handedOff?.id === id) {
        const { scanner } = handedOff
        handedOff = null
        return scanner
    }
    return null
}
