// PROTOTYPE, never merged: PostHog/michaelr-context#421. Rendered only by the prototype story, never by the app.
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { VIEWS_VARIANTS, ViewsVariant, isViewsVariant, setViewsVariant, useViewsState } from './viewsPrototypeStore'

export const VIEWS_VARIANT_LABELS: Record<ViewsVariant, string> = {
    A: 'A (Views in the sidebar)',
    B: 'B (View menu on the list)',
    C: 'C (One search bar)',
}

// Usage flags from the element pass on the ticket: flag and control only, never a number.
export const VIEWS_VARIANT_FLAGS: Record<ViewsVariant, string> = {
    A: 'element pass pending',
    B: 'element pass pending',
    C: 'element pass pending',
}

function step(current: ViewsVariant, by: number): ViewsVariant {
    const index = VIEWS_VARIANTS.indexOf(current)
    const count = VIEWS_VARIANTS.length
    return VIEWS_VARIANTS[(index + by + count) % count]
}

function isEditable(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
    )
}

export function ViewsPrototypeSwitcher(): JSX.Element {
    const { variant } = useViewsState()
    const { searchParams } = useValues(router)

    useEffect(() => {
        if (isViewsVariant(searchParams.views) && searchParams.views !== variant) {
            setViewsVariant(searchParams.views, false)
        }
    }, [searchParams.views, variant])

    useEffect(() => {
        const onKey = (event: KeyboardEvent): void => {
            if (isEditable(event.target) || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) {
                return
            }
            setViewsVariant(step(variant, event.key === 'ArrowLeft' ? -1 : 1))
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [variant])

    return (
        <div
            className="fixed bottom-4 left-1/2 z-[9999] flex -translate-x-1/2 items-center gap-1 rounded-full border-2 border-[#f54e00] bg-[#151515] px-1 py-1 text-white shadow-lg"
            data-attr="prototype-variant-switcher"
        >
            <button
                type="button"
                aria-label="Previous variant"
                className="flex size-7 items-center justify-center rounded-full hover:bg-white/15"
                onClick={() => setViewsVariant(step(variant, -1))}
            >
                <IconChevronLeft />
            </button>
            <span className="flex max-w-[70vw] flex-col px-2 text-center leading-tight">
                <span className="text-xs font-semibold">Prototype · {VIEWS_VARIANT_LABELS[variant]}</span>
                <span className="text-[10px] text-white/70">{VIEWS_VARIANT_FLAGS[variant]}</span>
            </span>
            <button
                type="button"
                aria-label="Next variant"
                className="flex size-7 items-center justify-center rounded-full hover:bg-white/15"
                onClick={() => setViewsVariant(step(variant, 1))}
            >
                <IconChevronRight />
            </button>
        </div>
    )
}
