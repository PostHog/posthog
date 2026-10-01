import type { ReactNode } from 'react'

export type ActivityStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface ActivityProps {
    id: string
    title: ReactNode
    subtitle?: ReactNode
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
