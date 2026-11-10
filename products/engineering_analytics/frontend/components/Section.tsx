import { ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

function sectionDomId(id: string): string {
    return `ea-section-${id}`
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
    note?: ReactNode
    right?: ReactNode
    busy?: boolean
    children: ReactNode
}): JSX.Element {
    return (
        <section id={sectionDomId(id)} className="scroll-mt-14" aria-busy={busy}>
            <div className="mb-2 flex flex-wrap items-baseline gap-2.5">
                <h2 className="m-0 text-base font-semibold">{title}</h2>
                {note && <span className="text-xs text-tertiary">{note}</span>}
                {busy && <Spinner className="text-sm text-secondary" />}
                {right && <span className="ml-auto max-w-full text-xs">{right}</span>}
            </div>
            <div className={cn('transition-opacity', busy && 'pointer-events-none opacity-60')}>{children}</div>
        </section>
    )
}
