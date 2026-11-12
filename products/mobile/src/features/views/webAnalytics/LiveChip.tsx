import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { useLiveUsersOnline } from '@/features/live/hooks'
import { groupThousands } from '@/model/adapters/text'
import { LiveDot } from '@/ui/LiveDot'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { liveHref } from '../viewRoutes'

/** Users online beside the Web analytics title. A tap opens Live. */
export function LiveChip(): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const { count, reconnecting, screenActive } = useLiveUsersOnline()
    const label = count !== null ? `${groupThousands(count)} online` : reconnecting ? 'Reconnecting…' : 'Live'
    return (
        <Pressable44
            onPress={() => router.push(liveHref({ from: 'web_analytics' }))}
            accessibilityRole="button"
            accessibilityLabel={label === 'Live' ? label : `Live, ${label}`}
            accessibilityHint="Opens Live"
            pressedBackground={colors.pressed}
            style={styles.chip}
            testID="web-analytics-live-chip"
        >
            <LiveDot on={count !== null} animate={screenActive} />
            <Text style={styles.text} numberOfLines={1}>
                {label}
            </Text>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        height: 34,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    text: {
        ...type.buttonSmall,
        fontSize: 14,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
}))
