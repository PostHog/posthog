// PROTOTYPE (ticket #385), throwaway. The floating bar is not part of any design being evaluated.
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonSelect, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DEMO_PERSON_UUID, JOURNEY_CASES, JOURNEY_VARIANTS, useEmailJourneyPrototype } from './useEmailJourneyPrototype'

export function JourneyPrototypeSwitcher(): JSX.Element | null {
    const prototype = useEmailJourneyPrototype()
    const { variant, journeyCase, set } = prototype
    const index = JOURNEY_VARIANTS.findIndex((v) => v.key === variant)

    const cycle = (step: number): void => {
        const next = JOURNEY_VARIANTS[(index + step + JOURNEY_VARIANTS.length) % JOURNEY_VARIANTS.length]
        set({ variant: next.key, link: null })
    }

    useEffect(() => {
        const onKey = (event: KeyboardEvent): void => {
            const target = event.target as HTMLElement | null
            if (target?.closest('input, textarea, [contenteditable="true"]')) {
                return
            }
            if (event.key === 'ArrowLeft') {
                cycle(-1)
            } else if (event.key === 'ArrowRight') {
                cycle(1)
            }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    })

    if (!variant) {
        return null
    }
    const current = JOURNEY_VARIANTS[index]

    return (
        <>
            {/* Room under the page, so the bar never covers its last lines. */}
            <div className="h-28" />
            <div
                className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[1000] flex flex-wrap items-center justify-center gap-3 rounded-lg border-2 border-black bg-black text-white px-3 py-2 shadow-lg max-w-[95vw]"
                data-attr="prototype-switcher"
            >
                <div className="flex items-center gap-1">
                    <button type="button" className="text-white p-1 cursor-pointer" onClick={() => cycle(-1)}>
                        <IconChevronLeft className="text-lg" />
                    </button>
                    <span className="font-semibold text-sm whitespace-nowrap">
                        {current.key === 'today' ? 'Today' : current.key} ({current.name})
                    </span>
                    <button type="button" className="text-white p-1 cursor-pointer" onClick={() => cycle(1)}>
                        <IconChevronRight className="text-lg" />
                    </button>
                </div>
                <div className="flex items-center gap-2 text-xs bg-white text-black rounded px-2 py-1">
                    <span className="font-semibold">Simulate</span>
                    <LemonSelect
                        size="xsmall"
                        value={journeyCase}
                        onChange={(value) => set({ case: value === 'full' ? null : value, link: null })}
                        options={JOURNEY_CASES.map((c) => ({ value: c.key, label: c.label }))}
                    />
                    <span className="text-secondary">|</span>
                    <span className="font-semibold">Entry</span>
                    <Link to={`${prototype.withParams(urls.personByUUID(DEMO_PERSON_UUID))}#activeTab=emails`}>
                        Person's Emails tab
                    </Link>
                    <Link to={prototype.withParams(urls.transactionalEmailLogEntry('prototype'))}>Send detail</Link>
                </div>
            </div>
        </>
    )
}
