// PROTOTYPE (throwaway, never merged): the floating variant switcher. It renders only inside the prototype
// pages, which exist only on branch prototype/messaging-overview-calendar.
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

export interface PrototypeVariant {
    key: string
    name: string
    // Usage-brief flags this variant trips, with the control, never numbers: the branch is public.
    flags?: string
}

export function usePrototypeVariant(variants: PrototypeVariant[]): PrototypeVariant {
    const { searchParams } = useValues(router)
    return variants.find((variant) => variant.key === searchParams.variant) ?? variants[0]
}

function selectVariant(key: string): void {
    const { location, searchParams, hashParams } = router.values
    router.actions.replace(location.pathname, { ...searchParams, variant: key }, hashParams)
}

export function PrototypeSwitcher({ variants, page }: { variants: PrototypeVariant[]; page: string }): JSX.Element {
    const current = usePrototypeVariant(variants)
    const index = variants.indexOf(current)
    const step = (by: number): void => selectVariant(variants[(index + by + variants.length) % variants.length].key)

    useEffect(() => {
        const onKey = (event: KeyboardEvent): void => {
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            if (event.key === 'ArrowLeft') {
                step(-1)
            } else if (event.key === 'ArrowRight') {
                step(1)
            }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    })

    return (
        <div
            data-quill-inverted
            className="fixed bottom-4 left-1/2 z-[1000] flex -translate-x-1/2 items-center gap-1 rounded-full border bg-background px-2 py-1 text-foreground shadow-lg"
        >
            <Button size="icon-sm" aria-label="Previous variant" tooltip="Previous variant" onClick={() => step(-1)}>
                <IconChevronLeft />
            </Button>
            <div className="flex flex-col items-center px-2 text-center">
                <span className="text-xxs uppercase tracking-wide opacity-70">Prototype · {page}</span>
                <span className="text-sm font-semibold whitespace-nowrap">
                    {current.key} ({current.name})
                    {current.flags ? <span className="font-normal opacity-70"> · {current.flags}</span> : null}
                </span>
            </div>
            <Button size="icon-sm" aria-label="Next variant" tooltip="Next variant" onClick={() => step(1)}>
                <IconChevronRight />
            </Button>
        </div>
    )
}
