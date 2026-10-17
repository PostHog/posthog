import type { ChatSessionStatus } from '@/model/types'
import { colors } from '@/ui/tokens'

export interface SessionStatusDisplay {
    label: string
    dotColor: string
}

const SESSION_STATUS: Record<ChatSessionStatus, SessionStatusDisplay> = {
    working: { label: 'Working', dotColor: colors.blue },
    queued: { label: 'Queued', dotColor: colors.blue },
    starting: { label: 'Starting', dotColor: colors.blue },
    // The app's alert accent stands in for the web app's red, which this palette only has for diffs.
    failed: { label: 'Failed', dotColor: colors.orange },
    completed: { label: 'Completed', dotColor: colors.tertiary },
    stopped: { label: 'Stopped', dotColor: colors.tertiary },
    idle: { label: 'Idle', dotColor: colors.tertiary },
}

export function sessionStatusDisplay(status: ChatSessionStatus): SessionStatusDisplay {
    return SESSION_STATUS[status]
}
