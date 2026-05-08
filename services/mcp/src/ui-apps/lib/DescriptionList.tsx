import type { ReactElement, ReactNode } from 'react'

// TODO(quill): delete this file once @posthog/quill ships a `DescriptionList`
// (a.k.a. `KeyValueList` / `MetadataList`) primitive. Migration is then a
// single-line import swap to `@posthog/quill`.
//
// What's needed from Quill:
//   - A two-column read-only key/value layout. The label column is muted and
//     emphasised by typography (`font-medium`), the value column carries the
//     content in `--foreground`. This is the inverse of `Field` /
//     `FieldTitle` + `FieldDescription`, which is form-oriented (Label is
//     bound to an input, the title is the emphasised text and the description
//     is muted body copy). Adopting Field here would flip the visual
//     hierarchy.
//   - Aligned columns across rows. Rendering each row as a separate
//     `<Field orientation="horizontal">` does not share a grid track, so
//     labels of varying length wouldn't align. We rely on
//     `grid-cols-[auto_1fr]` (or `auto_1fr_auto_1fr` for `columns={2}`) plus
//     `display: contents` on the row wrapper so each label/value pair
//     participates in the parent grid.
//   - Semantic `<dl>/<dt>/<dd>` markup (assistive tech announces these as
//     a description list). `Item` / `ItemTitle` / `ItemDescription` renders
//     `<div>` and is row-per-item rather than tabular, so it isn't a fit.
//   - Optional `columns: 1 | 2` prop for compact layouts, and `value:
//     ReactNode` so callers can embed badges/links.
//
// In the meantime this file is built on Quill's `cn()` and design tokens
// (`text-muted-foreground`, `text-foreground`, `--text-sm`) so the visual
// language already matches what a future Quill primitive would ship.
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
                    <dd className="min-w-0 text-foreground">{item.value}</dd>
                </div>
            ))}
        </dl>
    )
}
