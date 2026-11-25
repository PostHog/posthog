import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { formatClock } from '@/lib/dates'
import { useClockPreference } from '@/lib/useClockPreference'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

export function MessageTime({ timestamp }: { timestamp?: string }): ReactElement | null {
    const styles = useStyles()
    const uses24hourClock = useClockPreference()
    const date = timestamp ? new Date(timestamp) : null
    if (!date || !Number.isFinite(date.getTime())) return null

    return <Text style={styles.time}>{formatClock(date, uses24hourClock)}</Text>
}

const useStyles = createStyles(({ colors }) => ({
    time: { ...type.meta, color: colors.muted, lineHeight: 32 },
}))
