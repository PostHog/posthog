import { type ReactNode } from 'react'

import { JumpingLogomark } from 'lib/brand/JumpingLogomark'

// Logic-free welcome header: the jumping logomark, a headline, and a subheadline. Mirrors the look of
// scenes/max/Intro.tsx without its conversation coupling — the caller passes the (already-chosen) headline
// and may append extras (notices, changelog) via `children`.

export interface WelcomeProps {
    headline: string
    /** Defaults to the PostHog AI tagline; pass `null` to hide it entirely. */
    subheadline?: string | null
    /** Rendered after the header — e.g. a liability notice or changelog the consumer owns. */
    children?: ReactNode
}

export function Welcome({
    headline,
    subheadline = 'Build something people want.',
    children,
}: WelcomeProps): JSX.Element {
    return (
        <>
            <JumpingLogomark className="flex *:h-full *:w-12 p-2" />
            <div className="text-center mb-1">
                <h2 className="text-xl @2xl/main-content:text-2xl font-bold mb-2 text-balance">{headline}</h2>
                {subheadline && <div className="text-sm italic text-tertiary text-pretty py-0.5">{subheadline}</div>}
            </div>
            {children}
        </>
    )
}
