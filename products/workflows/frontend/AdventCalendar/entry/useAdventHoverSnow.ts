import { MouseEvent, useEffect, useRef } from 'react'

import { retryImport } from 'lib/utils/retryImport'

export interface AdventHoverSnowProps {
    onMouseEnter: (event: MouseEvent<HTMLElement>) => void
    onMouseLeave: () => void
}

const loadSnow = (): Promise<typeof import('./adventHoverSnow')> => retryImport(() => import('./adventHoverSnow'))

function prefersReducedMotion(): boolean {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useAdventHoverSnow(): AdventHoverSnowProps {
    const hovering = useRef(false)

    const stop = (): void => {
        if (hovering.current) {
            hovering.current = false
            void loadSnow().then((snow) => snow.hideAdventHoverSnow())
        }
    }

    useEffect(() => stop, [])

    return {
        onMouseEnter: (event) => {
            if (prefersReducedMotion()) {
                return
            }
            hovering.current = true
            const trigger = event.currentTarget.getBoundingClientRect()
            void loadSnow().then((snow) => hovering.current && snow.showAdventHoverSnow(trigger))
        },
        onMouseLeave: stop,
    }
}
