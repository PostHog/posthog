import { createContext } from 'react'

import type { WidgetFrameApi } from '../generated/api.schemas'

export interface WidgetFrameSession {
    revision: string
    read: (
        slot: string,
        offset: number,
        limit: number,
        load: (offset: number, limit: number, runId?: string) => Promise<WidgetFrameApi>
    ) => Promise<WidgetFrameApi>
}

export const WidgetFrameSessionContext = createContext<
    (nodeId: string, versionId: string | null) => WidgetFrameSession
>(() => ({ revision: '', read: (_slot, offset, limit, load) => load(offset, limit) }))
