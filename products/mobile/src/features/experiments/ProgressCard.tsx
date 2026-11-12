import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { formatCount, type ProgressModel, progressLabel } from './detailModel'

/** Exposures against the recommended sample size. A tap explains the target. */
export function ProgressCard({ progress, onPress }: { progress: ProgressModel; onPress: () => void }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const reached = progress.state === 'reached'
    const right = progressLabel(progress)
    const amount =
        progress.recommended === null
            ? `${formatCount(progress.current)}`
            : `${formatCount(progress.current)} of ${formatCount(progress.recommended)}`
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={`${amount} exposures, ${right}`}
            accessibilityHint="Explains the target"
            pressedBackground={colors.pressed}
            style={styles.card}
            testID="experiment-progress"
        >
            <View style={styles.label}>
                <Text style={styles.amount} numberOfLines={1}>
                    <Text style={styles.strong}>{amount}</Text> exposures
                </Text>
                <Text style={[styles.right, reached && styles.reached]} numberOfLines={1}>
                    {right}
                </Text>
            </View>
            <View style={styles.track}>
                <View
                    style={[
                        styles.fill,
                        reached && styles.fillReached,
                        { width: `${Math.round(Math.min(1, progress.fill) * 1000) / 10}%` },
                    ]}
                />
            </View>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        paddingHorizontal: 14,
        paddingTop: 14,
        paddingBottom: 16,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        gap: 12,
    },
    label: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
    },
    amount: {
        ...type.metaSmall,
        color: colors.ink,
        flexShrink: 1,
    },
    strong: {
        fontWeight: '600',
    },
    right: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.secondary,
    },
    reached: {
        color: colors.diffGreen,
    },
    track: {
        height: 6,
        borderRadius: 3,
        backgroundColor: colors.sunken,
        overflow: 'hidden',
    },
    fill: {
        height: 6,
        borderRadius: 3,
        backgroundColor: colors.ink,
    },
    fillReached: {
        backgroundColor: colors.diffGreen,
    },
}))
