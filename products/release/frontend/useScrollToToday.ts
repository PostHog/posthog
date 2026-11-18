import { useEffect, useRef } from 'react'

import { dayjs } from 'lib/dayjs'

import { Scale, todayScrollLeft } from './releaseTracks'

export function useScrollToToday(
    container: HTMLElement | null,
    scale: Scale,
    hasStickyColumn: boolean,
    ready: boolean
): void {
    const scrolled = useRef<HTMLElement | null>(null)
    useEffect(() => {
        if (!ready) {
            return
        }
        const viewport = container?.querySelector<HTMLElement>('[data-slot=table-viewport]')
        if (!viewport || !viewport.clientWidth || scrolled.current === viewport) {
            return
        }
        scrolled.current = viewport
        const sticky = hasStickyColumn ? (container?.querySelector('thead th')?.getBoundingClientRect().width ?? 0) : 0
        const left = todayScrollLeft(scale, viewport.clientWidth, sticky, dayjs())
        if (left !== null) {
            viewport.scrollLeft = left
        }
    })
}
