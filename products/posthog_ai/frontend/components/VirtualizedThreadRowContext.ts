import { createContext } from 'react'

export interface VirtualizedThreadRowContextValue {
    index: number
}

/** The index of the row a `VirtualizedThread.Row` renders in, in both virtualized and flow mode. */
export const VirtualizedThreadRowContext = createContext<VirtualizedThreadRowContextValue | null>(null)
