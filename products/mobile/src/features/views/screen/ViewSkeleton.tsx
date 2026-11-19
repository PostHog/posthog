import type { ReactElement } from 'react'
import { type DimensionValue, View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { radii } from '@/ui/tokens'

function Bar({ width, height, radius = 6 }: { width: DimensionValue; height: number; radius?: number }): ReactElement {
    const styles = useStyles()
    return <View style={[styles.bar, { width, height, borderRadius: radius }]} />
}

/** One tile's placeholder at the height of a chart tile, so a tile does not jump when its data lands. */
export function TileSkeleton({ height = 160 }: { height?: number }): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.tileBody}>
            <Bar width="100%" height={height} radius={8} />
        </View>
    )
}

/**
 * A first load with no cached data. The blocks follow the real layout: title, status line, range, then cards. They do
 * not shimmer, so reduce motion needs no special case.
 */
export function ViewSkeleton({ cards = 3 }: { cards?: number }): ReactElement {
    const styles = useStyles()
    return (
        <View accessibilityLabel="Loading" accessibilityRole="progressbar" testID="view-loading">
            <Bar width="62%" height={28} radius={8} />
            <View style={styles.status}>
                <Bar width="34%" height={12} />
            </View>
            <View style={styles.range}>
                <Bar width={128} height={40} radius={radii.pill} />
            </View>
            {Array.from({ length: cards }, (_, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: placeholders have no identity.
                <View key={index} style={styles.card}>
                    <Bar width="48%" height={14} />
                    <View style={styles.cardBody}>
                        <Bar width="100%" height={index === 0 ? 72 : 140} radius={8} />
                    </View>
                </View>
            ))}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    bar: {
        backgroundColor: colors.sunken,
    },
    status: {
        marginTop: 10,
    },
    range: {
        marginTop: 16,
        marginBottom: 20,
    },
    card: {
        padding: 14,
        marginBottom: 10,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    cardBody: {
        marginTop: 14,
    },
    tileBody: {
        paddingTop: 2,
    },
}))
