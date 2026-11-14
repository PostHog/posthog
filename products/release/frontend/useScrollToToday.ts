import { useEffect, useRef } from 'react'

import { dayjs } from 'lib/dayjs'

import { Scale, x } from './releaseTracks'

const PAST_SHARE = 0.65

export function useScrollToToday(container: HTMLElement | null, scale: Scale, ready: boolean): void {
    const done = useRef(false)
    useEffect(() => {
        if (done.current || !ready) {
            return
        }
        const viewport = container?.querySelector<HTMLElement>('[data-slot=table-viewport]')
        if (!viewport || !viewport.clientWidth) {
            return
        }
        done.current = true
        const sticky = container?.querySelector('thead th')?.getBoundingClientRect().width ?? 0
        const visible = viewport.clientWidth - sticky
        const today = x(dayjs().toISOString(), scale) + scale.day / 2
        if (today > visible - scale.day) {
            viewport.scrollLeft = Math.max(0, today - visible * PAST_SHARE)
        }
    })
}
