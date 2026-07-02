// The section rhythm every entity page shares: an anchored <section> with a compact title row, and a
// sticky jumper that scrolls between them. Facets (failures / cost / activity / …) are sections on
// one page, never separate places.

import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

function sectionDomId(id: string): string {
    return `ea-section-${id}`
}

export function Section({
    id,
    title,
    note,
    right,
    children,
}: {
    id: string
    title: string
    /** Muted one-liner after the title — what this section is and its caveat. */
    note?: ReactNode
    right?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <section id={sectionDomId(id)} className="scroll-mt-14">
            <div className="mb-2 flex items-baseline gap-2.5">
                <h2 className="m-0 text-base font-semibold">{title}</h2>
                {note && <span className="text-xs text-tertiary">{note}</span>}
                {right && <span className="ml-auto text-xs">{right}</span>}
            </div>
            {children}
        </section>
    )
}

/** Quiet in-page jump links — deliberately not a tab bar: sections stack on one page, nothing switches. */
export function SectionNav({ items }: { items: { id: string; label: string }[] }): JSX.Element {
    return (
        <div className="sticky top-0 z-10 -mx-1 flex flex-wrap items-center gap-0.5 bg-primary px-1 py-1.5">
            <span className="mr-1.5 text-xs text-tertiary">Jump to</span>
            {items.map((item) => (
                <LemonButton
                    key={item.id}
                    size="xsmall"
                    onClick={() =>
                        document
                            .getElementById(sectionDomId(item.id))
                            ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    }
                >
                    {item.label}
                </LemonButton>
            ))}
        </div>
    )
}
