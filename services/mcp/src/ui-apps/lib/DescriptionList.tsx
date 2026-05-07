import type { ReactElement, ReactNode } from 'react'

// TODO(quill): replace with @posthog/quill DescriptionList (or equivalent)
// once Quill ships one. The Field/FieldLabel/FieldDescription primitives are
// form-oriented; this is the read-only list-of-key-value-pairs counterpart.
// Built on Quill tokens so the visual language already matches.
import { cn } from '@posthog/quill'

export interface DescriptionListItem {
    label: string
    value: ReactNode
}

export interface DescriptionListProps {
    items: DescriptionListItem[]
    columns?: 1 | 2
    className?: string
}

export function DescriptionList({ items, columns = 1, className }: DescriptionListProps): ReactElement {
    const filtered = items.filter((item) => item.value != null && item.value !== '')
    if (filtered.length === 0) {
        return <></>
    }

    return (
        <dl
            className={cn(
                'grid gap-x-4 gap-y-2 text-sm',
                columns === 2 ? 'grid-cols-[auto_1fr_auto_1fr]' : 'grid-cols-[auto_1fr]',
                className
            )}
        >
            {filtered.map((item) => (
                <div key={item.label} className="contents">
                    <dt className="text-muted-foreground font-medium whitespace-nowrap">{item.label}</dt>
                    <dd className="text-foreground">{item.value}</dd>
                </div>
            ))}
        </dl>
    )
}
