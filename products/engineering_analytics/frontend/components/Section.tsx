// The section rhythm every entity page shares: an anchored <section> with a compact title row, and a
// sticky segmented jumper that scrolls between them. Facets (failures / cost / activity / …) are
// sections on one page, never separate places.

import { ReactNode, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

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

export function SectionNav({ items }: { items: { id: string; label: string }[] }): JSX.Element {
    // Which section was last jumped to — pure view state, no reason to survive the page.
    const [active, setActive] = useState(items[0]?.id)
    return (
        <div className="sticky top-0 z-10 -mx-1 bg-primary px-1 py-2">
            <LemonSegmentedButton
                size="small"
                value={active}
                onChange={(value) => {
                    setActive(value)
                    document.getElementById(sectionDomId(value))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
                options={items.map((item) => ({ value: item.id, label: item.label }))}
            />
        </div>
    )
}
