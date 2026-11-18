import { ReactNode } from 'react'

/** The shaded block at the top of a card that names what will be created and how it behaves. */
export function SuggestionDraftSummary({ name, children }: { name: string; children?: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5 rounded bg-surface-secondary px-2 py-1.5">
            <span className="text-sm font-medium">{name}</span>
            {children}
        </div>
    )
}
