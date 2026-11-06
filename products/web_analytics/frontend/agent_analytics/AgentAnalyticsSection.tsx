import clsx from 'clsx'
import { ReactNode } from 'react'

export interface AgentAnalyticsSectionProps {
    title: string
    description?: ReactNode
    right?: ReactNode
    children: ReactNode
    className?: string
}

export const AgentAnalyticsSection = ({
    title,
    description,
    right,
    children,
    className,
}: AgentAnalyticsSectionProps): JSX.Element => (
    <section className={clsx('flex flex-col gap-3', className)}>
        <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 flex-col gap-1">
                <h2 className="text-lg font-semibold">{title}</h2>
                {description ? <p className="m-0 max-w-3xl text-sm text-secondary">{description}</p> : null}
            </div>
            {right}
        </div>
        {children}
    </section>
)
