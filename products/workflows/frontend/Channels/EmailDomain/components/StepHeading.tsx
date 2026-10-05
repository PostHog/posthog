import { ComponentType, ReactNode } from 'react'

import { Spinner } from '@posthog/lemon-ui'

interface StepHeadingProps {
    Hoggie: ComponentType<{ className?: string }>
    title: ReactNode
    lead?: ReactNode
    busy?: boolean
}

export function StepHeading({ Hoggie, title, lead, busy }: StepHeadingProps): JSX.Element {
    return (
        <header className="flex flex-col items-center text-center gap-4">
            <Hoggie className="w-28 @md:w-36" />
            <h1 className="m-0 text-2xl @md:text-3xl font-bold leading-tight text-balance flex items-center justify-center gap-3 flex-wrap">
                {busy && <Spinner className="text-xl" />}
                {title}
            </h1>
            {lead && <p className="m-0 text-base text-secondary max-w-prose text-balance">{lead}</p>}
        </header>
    )
}
