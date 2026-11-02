import { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

import { SAVING_COLUMNS_CLASS } from './SuggestionRow'

export interface SuggestedModelsSectionProps {
    title: string
    description: string
    children: ReactNode
}

export function SuggestedModelsSection({ title, description, children }: SuggestedModelsSectionProps): JSX.Element {
    return (
        <section aria-label={title}>
            <div className={cn('grid grid-cols-1 items-end px-3 pt-4 pb-1', SAVING_COLUMNS_CLASS)}>
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <h4 className="m-0 text-sm font-semibold">{title}</h4>
                    <span className="text-xs text-secondary">{description}</span>
                </div>
                <span className="hidden text-right text-xs text-secondary @min-[36rem]/suggestions:block">
                    Saves a month
                </span>
            </div>
            <div className="divide-y divide-primary">{children}</div>
        </section>
    )
}
