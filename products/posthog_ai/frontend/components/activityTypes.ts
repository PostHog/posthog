import type { ReactNode } from 'react'

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
    /**
     * Opens the details by this rule instead of the status: they open while it is true and close when it turns
     * false. A reader's toggle holds until it changes.
     */
    defaultOpen?: boolean
    onToggleDetails?: (expanded: boolean) => void
}
