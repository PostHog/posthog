import type { ComponentType, ReactNode } from 'react'

import type { HoggiePngProps } from 'lib/brand/hoggies'

/** The title and lead every setup step opens with, beside a hedgehog unless the step shows its own. */
export function SetupStepHero({
    Hedgehog,
    title,
    lead,
}: {
    Hedgehog?: ComponentType<Pick<HoggiePngProps, 'className' | 'loading'>>
    title: ReactNode
    lead: ReactNode
}): JSX.Element {
    return (
        <div className="flex items-center gap-4">
            {/* The hedgehog is the first thing to go when the window is narrow, so the title keeps its width.
                It loads eagerly because a lazy image in `display: none` never gets fetched. */}
            {Hedgehog ? (
                <Hedgehog className="hidden w-20 shrink-0 @min-[36rem]/setup-mode:block" loading="eager" />
            ) : null}
            <div className="flex min-w-0 flex-col gap-1">
                <h2 className="m-0 text-2xl font-semibold">{title}</h2>
                <p className="m-0 text-sm text-secondary">{lead}</p>
            </div>
        </div>
    )
}
