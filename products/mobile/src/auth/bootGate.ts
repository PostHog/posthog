import { create } from 'zustand'

// A hung request must not trap the user on the splash; after this the first screen shows its own loading state.
export const SPLASH_TIMEOUT_MS = 8_000

interface BootGateState {
    firstScreenReady: boolean
    markFirstScreenReady: () => void
}

export const useBootGate = create<BootGateState>()((set) => ({
    firstScreenReady: false,
    markFirstScreenReady: () => set({ firstScreenReady: true }),
}))

export interface SplashGateInput {
    sessionReady: boolean
    firstScreenReady: boolean
    firstSegment: string | undefined
    timedOut: boolean
}

// The index route has no segment and redirects to the inbox, so both hold the splash until the inbox loads.
function holdsSplash(firstSegment: string | undefined): boolean {
    return firstSegment === undefined || firstSegment === 'inbox'
}

export function shouldHideSplash({ sessionReady, firstScreenReady, firstSegment, timedOut }: SplashGateInput): boolean {
    if (!sessionReady) {
        return false
    }
    return firstScreenReady || timedOut || !holdsSplash(firstSegment)
}
