import { ReactNode } from 'react'

import { LemonCard } from '@posthog/lemon-ui'

export interface SetupStepCardProps {
    title: ReactNode
    description: ReactNode
    children: ReactNode
    dataAttr: string
}

export function SetupStepCard({ title, description, children, dataAttr }: SetupStepCardProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 min-w-0" data-attr={dataAttr}>
            <div className="flex flex-col gap-1">
                <h3 className="font-semibold m-0">{title}</h3>
                <p className="m-0">{description}</p>
            </div>
            {children}
        </LemonCard>
    )
}
