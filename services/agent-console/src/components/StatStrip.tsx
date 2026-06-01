/**
 * `<StatStrip />` — 4-up KPI row for the top of list pages.
 *
 * Minimal: each tile is one label + one value + an optional sublabel.
 * Numbers are tabular so they scan cleanly when they change.
 *
 * Designed to compose: the same tile shape works at the top of the
 * agents list (fleet stats) and on the agent detail page (per-agent
 * stats) once we have per-agent rollups.
 */

import type { ReactNode } from 'react'

export interface StatTile {
    label: string
    value: ReactNode
    /** Short helper line below the value. */
    hint?: string
    /**
     * Visual emphasis: `'default'` is the resting tone; `'attention'` is
     * used when the value is non-zero AND the metric implies "look at me"
     * (e.g. unhealthy count, pending approvals).
     */
    tone?: 'default' | 'attention'
}

export interface StatStripProps {
    tiles: StatTile[]
    className?: string
    /**
     * Visual density. `'default'` is the landing-page hero (text-xl values);
     * `'sm'` is a compact variant for embedded contexts (text-base values,
     * tighter padding) so the strip reads as a status row rather than a hero.
     */
    size?: 'default' | 'sm'
}

export function StatStrip({ tiles, className, size = 'default' }: StatStripProps): React.ReactElement {
    const tilePad = size === 'sm' ? 'px-3 py-1.5' : 'px-4 py-3'
    const valueText = size === 'sm' ? 'text-sm' : 'text-xl'
    return (
        <div
            className={
                'grid grid-cols-2 gap-0 overflow-hidden rounded-md border border-border bg-card sm:grid-cols-4' +
                (className ? ` ${className}` : '')
            }
            data-slot="stat-strip"
        >
            {tiles.map((tile, i) => (
                <div
                    key={tile.label}
                    className={
                        tilePad +
                        (i > 0 ? ' border-l border-border' : '') +
                        (i >= 2 ? ' border-t border-border sm:border-t-0' : '')
                    }
                >
                    <div className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">{tile.label}</div>
                    <div
                        className={
                            'mt-0.5 font-mono tabular-nums leading-tight ' +
                            valueText +
                            ' ' +
                            (tile.tone === 'attention' ? 'text-warning-foreground' : 'text-foreground')
                        }
                    >
                        {tile.value}
                    </div>
                    {tile.hint ? (
                        <div className="mt-0.5 text-[0.6875rem] text-muted-foreground">{tile.hint}</div>
                    ) : null}
                </div>
            ))}
        </div>
    )
}
