import { useEffect, useRef } from 'react'

import { track } from '@/lib/analytics'
import type { PinKind, ViewEntry } from '@/model/views'

export type WidgetFamily = 'small' | 'medium' | 'large'

const FAMILIES: readonly WidgetFamily[] = ['small', 'medium', 'large']

export function widgetFamilyParam(value: string | string[] | undefined): WidgetFamily | null {
    const first = Array.isArray(value) ? value[0] : value
    return FAMILIES.find((family) => family === first) ?? null
}

export function useWidgetOpenedEvent(kind: PinKind, from: ViewEntry, family: WidgetFamily | null): void {
    const sent = useRef(false)
    useEffect(() => {
        if (sent.current || from !== 'widget') {
            return
        }
        sent.current = true
        track('mobile_widget_opened', { kind, family: family ?? undefined })
    }, [kind, from, family])
}
