// Anchored page sections with a compact title row.

import { ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

function sectionDomId(id: string): string {
    return `ea-section-${id}`
}

export function scrollToSection(id: string): void {
    document.getElementById(sectionDomId(id))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export function Section({
    id,
    title,
    note,
    right,
    busy = false,
    children,
}: {
    id: string
    title: string
    /** Muted caveat after the title. Only for load-bearing context the data can't show (scope, inclusion
     *  criteria, a legend) — never a restatement of the title or an interaction hint. */
    note?: ReactNode
    right?: ReactNode
    /** Reloading with data already on screen (e.g. the window changed): a spinner by the title and dimmed
     *  content, so the stale data reads as "updating" instead of silently swapping. */
    busy?: boolean
    children: ReactNode
}): JSX.Element {
    return (
        <section id={sectionDomId(id)} className="scroll-mt-14" aria-busy={busy}>
            <div className="mb-2 flex items-baseline gap-2.5">
                <h2 className="m-0 text-base font-semibold">{title}</h2>
                {note && <span className="text-xs text-tertiary">{note}</span>}
                {busy && <Spinner className="text-sm text-secondary" />}
                {right && <span className="ml-auto text-xs">{right}</span>}
            </div>
            <div className={cn('transition-opacity', busy && 'pointer-events-none opacity-60')}>{children}</div>
        </section>
    )
}
