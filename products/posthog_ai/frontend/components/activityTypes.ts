import type { ReactNode } from 'react'

// A long command, query or thought scrolls inside its row instead of filling the thread.
export const ACTIVITY_DETAILS_BOUND_CLASS = 'max-h-80 overflow-y-auto overscroll-contain'

export type ActivityStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface ActivityProps {
    id: string
    title: ReactNode
    subtitle?: ReactNode
    /** Wraps a long title instead of truncating it, for a row that carries a message rather than a tool call. */
    wrapTitle?: boolean
    status: ActivityStatus
    icon?: ReactNode
    animate?: boolean
    showCompletionIcon?: boolean
    showProgressIcon?: boolean
    failedIcon?: ReactNode
    substeps?: string[]
    details?: ReactNode
    children?: ReactNode
    autoExpand?: boolean
    onToggleDetails?: (expanded: boolean) => void
}
