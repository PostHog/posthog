// PROTOTYPE (ticket #320), throwaway. The floating bar is not part of any design being evaluated.
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { PROTOTYPE_VARIANTS, useSendFromCodePrototype } from './useSendFromCodePrototype'

export function PrototypeSwitcher(): JSX.Element | null {
    const prototype = useSendFromCodePrototype()
    const { variant, set } = prototype
    const index = PROTOTYPE_VARIANTS.findIndex((v) => v.key === variant)

    const cycle = (step: number): void => {
        const next = PROTOTYPE_VARIANTS[(index + step + PROTOTYPE_VARIANTS.length) % PROTOTYPE_VARIANTS.length]
        set({ variant: next.key, view: null })
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
    const current = PROTOTYPE_VARIANTS[index]

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
                <div className="flex flex-wrap items-center gap-2 text-xs bg-white text-black rounded px-2 py-1">
                    <span className="font-semibold">Simulate</span>
                    <span>Domain</span>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={prototype.domain}
                        onChange={(domain) => set({ domain })}
                        options={[
                            { value: 'none', label: 'None' },
                            { value: 'pending', label: 'Pending' },
                            { value: 'verified', label: 'Verified' },
                        ]}
                    />
                    <span>Emails</span>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={prototype.emails}
                        onChange={(emails) => set({ emails })}
                        options={[
                            { value: 'none', label: 'None yet' },
                            { value: 'some', label: 'Some' },
                        ]}
                    />
                    <span>First send</span>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={prototype.firstSend}
                        onChange={(firstSend) => set({ firstSend })}
                        options={[
                            { value: 'waiting', label: 'Waiting' },
                            { value: 'arrived', label: 'Arrived' },
                        ]}
                    />
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => set({ domain: null, emails: null, firstSend: null, view: null })}
                    >
                        Reset
                    </LemonButton>
                </div>
            </div>
        </>
    )
}
