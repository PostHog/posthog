import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { LiveDot } from '@/ui/LiveDot'
import { createStyles } from '@/ui/theme'
import { fonts, radii, type } from '@/ui/tokens'

import { formatCount } from './detailModel'

const BAR_MAX = 36
const BARS = 8

interface WatchingCardProps {
    /** Null until the first exposure read returns. */
    total: number | null
    /** Exposure totals of the reads on this visit, oldest first. */
    history: readonly number[]
    /** `Updated 12 s ago`, or null before the first read. */
    updated: string | null
    /** False while the screen or app is in the background, which pauses the reads. */
    live: boolean
}

/**
 * A just-launched experiment: exposures re-read every minute while the screen is open. It reads stored results only
 * and never starts a recalculation.
 */
export function WatchingCard({ total, history, updated, live }: WatchingCardProps): ReactElement {
    const styles = useStyles()
    const shown = history.slice(-BARS)
    const peak = Math.max(1, ...shown)
    return (
        <View style={styles.card} testID="experiment-watching" accessibilityLiveRegion="polite">
            <View style={styles.top}>
                <LiveDot on={live} animate />
                <Text style={styles.title}>Watching</Text>
                {updated ? (
                    <Text style={styles.updated} numberOfLines={1}>
                        {updated}
                    </Text>
                ) : null}
            </View>
            <Text style={styles.body}>
                First exposures arrive within minutes. This card stays fresh while the screen is open.
            </Text>
            <View style={styles.live}>
                <View>
                    <Text style={styles.number} testID="experiment-watching-total">
                        {total === null ? '—' : formatCount(total)}
                    </Text>
                    <Text style={styles.caption}>exposures so far</Text>
                </View>
                <View style={styles.bars} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
                    {shown.map((value, index) => (
                        <View
                            // biome-ignore lint/suspicious/noArrayIndexKey: bars are positions in a rolling window
                            key={index}
                            style={[
                                styles.bar,
                                index === shown.length - 1 && styles.barLatest,
                                { height: Math.max(3, Math.round((value / peak) * BAR_MAX)) },
                            ]}
                        />
                    ))}
                </View>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginTop: 12,
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.blueLight,
        backgroundColor: colors.blueHighlight,
        gap: 8,
    },
    top: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    title: {
        ...type.bodyStrong,
        color: colors.ink,
        flex: 1,
    },
    updated: {
        ...type.meta,
        color: colors.secondary,
    },
    body: {
        ...type.metaSmall,
        color: colors.muted,
    },
    live: {
        flexDirection: 'row',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        marginTop: 4,
    },
    number: {
        fontFamily: fonts.mono,
        fontSize: 28,
        fontWeight: '700',
        color: colors.ink,
    },
    caption: {
        ...type.meta,
        color: colors.secondary,
    },
    bars: {
        flexDirection: 'row',
        alignItems: 'flex-end',
        gap: 4,
        height: BAR_MAX,
    },
    bar: {
        width: 7,
        borderRadius: 2,
        backgroundColor: colors.blueLight,
    },
    barLatest: {
        backgroundColor: colors.blue,
    },
}))
