import type { ChatSessionStatus } from '@/model/types'
import type { ThemeColors } from '@/ui/theme'

export interface SessionStatusDisplay {
    label: string
    dotColor: string
}

const SESSION_STATUS: Record<ChatSessionStatus, { label: string; dot: keyof ThemeColors }> = {
    working: { label: 'Working', dot: 'blue' },
    queued: { label: 'Queued', dot: 'blue' },
    starting: { label: 'Starting', dot: 'blue' },
    // The app's alert accent stands in for the web app's red, which this palette only has for diffs.
    failed: { label: 'Failed', dot: 'orange' },
    completed: { label: 'Completed', dot: 'tertiary' },
    stopped: { label: 'Stopped', dot: 'tertiary' },
    idle: { label: 'Idle', dot: 'tertiary' },
}

export function sessionStatusDisplay(status: ChatSessionStatus, colors: ThemeColors): SessionStatusDisplay {
    const { label, dot } = SESSION_STATUS[status]
    return { label, dotColor: colors[dot] }
}
