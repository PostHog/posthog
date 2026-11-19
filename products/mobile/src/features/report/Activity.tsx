import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { formatActivityTime } from '@/lib/dates'
import { useNow } from '@/lib/useNow'
import type { ActivityEvent } from '@/model/types'
import { Avatar } from '@/ui/Avatar'
import { TimelineItem } from '@/ui/TimelineItem'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

interface ActivityProps {
    events: ActivityEvent[]
    viewerName: string
}

export function Activity({ events, viewerName }: ActivityProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const now = useNow()
    return (
        <View style={styles.section}>
            <View style={styles.header}>
                <Text style={styles.title} accessibilityRole="header">
                    Activity
                </Text>
                <Avatar name={viewerName} color={colors.avatarNeutral} size={28} fontSize={11} />
            </View>
            <View style={styles.timeline}>
                {events.map((event, index) => (
                    <TimelineItem
                        key={event.id}
                        text={event.text}
                        time={formatActivityTime(event.at, now)}
                        via={event.via}
                        isLast={index === events.length - 1}
                    />
                ))}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 24,
        paddingTop: 20,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    title: {
        ...type.sectionHeader,
        color: colors.muted,
    },
    timeline: {
        marginTop: 16,
    },
}))
