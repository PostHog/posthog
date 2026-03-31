import { ReactNode } from 'react'

import { LemonTableColumn } from 'lib/lemon-ui/LemonTable/types'

export type VirtualizedColumnSizing =
    | { type: 'fixed'; width: number }
    | { type: 'resizable'; width: number; minWidth: number; maxWidth?: number }
    | { type: 'flex'; minWidth: number }

export interface VirtualizedTableColumn<T extends Record<string, any>> extends Pick<
    LemonTableColumn<T, keyof T | undefined>,
    'key' | 'title' | 'align' | 'tooltip' | 'isHidden'
> {
    /** How the column width is determined */
    sizing: VirtualizedColumnSizing
    /** Render cell content */
    render: (record: T, recordIndex: number) => ReactNode
    /** Render header content (defaults to `title` if omitted) */
    renderHeader?: () => ReactNode
    /** Per-cell className */
    className?: string
}
