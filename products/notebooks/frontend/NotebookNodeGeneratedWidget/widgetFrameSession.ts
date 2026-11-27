import { createContext } from 'react'

import type { WidgetFrameApi } from '../generated/api.schemas'

export interface WidgetFrameSession {
    revision: string
    privateInputs?: {
        key: string
        sourceNames: ReadonlySet<string>
        compute: (slots: string[], signal: AbortSignal) => Promise<WidgetFrameApi[]>
    }
    read: (
        slot: string,
        offset: number,
        limit: number,
        load: (offset: number, limit: number) => Promise<WidgetFrameApi>
    ) => Promise<WidgetFrameApi>
}

export const WidgetFrameSessionContext = createContext<
    (nodeId: string, versionId: string | null) => WidgetFrameSession
>(() => ({ revision: '', read: (_slot, offset, limit, load) => load(offset, limit) }))
