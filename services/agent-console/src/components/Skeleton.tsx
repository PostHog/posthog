/**
 * `<Skeleton />` — neutral placeholder block. Layered-out copies form
 * each page's "shadow UI" so the layout doesn't jump when real data
 * arrives. Uses the global `animate-skeleton` shimmer from globals.css.
 */

'use client'

export function Skeleton({ className = '' }: { className?: string }): React.ReactElement {
    return <div aria-hidden="true" className={`animate-skeleton rounded bg-muted ${className}`} />
}
