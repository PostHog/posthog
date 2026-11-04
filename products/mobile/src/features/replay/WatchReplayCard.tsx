import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { PlayIcon } from '@/ui/icons/PlayIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface WatchReplayCardProps {
    onWatch: () => void
    disabled: boolean
}

export function WatchReplayCard({ onWatch, disabled }: WatchReplayCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.card}>
            <Pressable44
                onPress={onWatch}
                disabled={disabled}
                accessibilityRole="button"
                accessibilityLabel="Watch full replay"
                accessibilityState={{ disabled }}
                pressedBackground={colors.inkHover}
                style={styles.button}
                testID="session-watch-replay"
            >
                <PlayIcon size={iconSizes.control} color={colors.onInk} />
                <Text style={styles.label}>Watch full replay</Text>
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: { gap: 8 },
    button: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        backgroundColor: colors.ink,
        borderRadius: radii.card,
        paddingHorizontal: 16,
        paddingVertical: 14,
    },
    label: { ...type.rowTitle, color: colors.onInk, flexShrink: 1 },
}))
