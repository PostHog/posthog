import { useEffect, useRef } from 'react'

import { retryImport } from 'lib/utils/retryImport'

export interface AdventHoverSnowProps {
    onMouseEnter: () => void
    onMouseLeave: () => void
}

const loadSnowOrNothing = (): Promise<typeof import('./adventHoverSnow') | null> =>
    retryImport(() => import('./adventHoverSnow')).catch(() => null)

function prefersReducedMotion(): boolean {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useAdventHoverSnow(): AdventHoverSnowProps {
    const hovering = useRef(false)

    const stop = (): void => {
        if (hovering.current) {
            hovering.current = false
            void loadSnowOrNothing().then((snow) => snow?.hideAdventHoverSnow())
        }
    }

    useEffect(() => stop, [])

    return {
        onMouseEnter: () => {
            if (prefersReducedMotion()) {
                return
            }
            hovering.current = true
            void loadSnowOrNothing().then((snow) => hovering.current && snow?.showAdventHoverSnow())
        },
        onMouseLeave: stop,
    }
}
