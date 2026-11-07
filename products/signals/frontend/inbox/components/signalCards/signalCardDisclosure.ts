import { createContext, useContext } from 'react'

export interface SignalCardDisclosureState {
    expanded: boolean
    onChange: (expanded: boolean) => void
}

/** Set by a caller that collapses signal cards to their header, shared by the Lemon and quill card shells. */
export const SignalCardDisclosureContext = createContext<SignalCardDisclosureState | null>(null)

export function useSignalCardDisclosure(): SignalCardDisclosureState | null {
    return useContext(SignalCardDisclosureContext)
}
