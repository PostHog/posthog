import type { ReactElement } from 'react'
import { View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { radii } from '@/ui/tokens'

import { PIN_CHART_HEIGHT, PIN_NUMBER_HEIGHT, PIN_ROW_HEIGHT } from './PinCard'

/** The first load with nothing cached: blocks in the shape of the list, so the content lands where they were. */
export function ViewsSkeleton(): ReactElement {
    const styles = useStyles()
    return (
        <View
            style={styles.root}
            accessibilityLabel="Loading your views"
            accessibilityRole="progressbar"
            testID="views-loading"
        >
            <View style={[styles.block, styles.search]} />
            <View style={[styles.block, styles.eyebrow]} />
            <View style={styles.cards}>
                <SkeletonCard height={PIN_ROW_HEIGHT} />
                <SkeletonCard height={PIN_NUMBER_HEIGHT} body="number" />
                <SkeletonCard height={PIN_CHART_HEIGHT} body="chart" />
            </View>
        </View>
    )
}

function SkeletonCard({ height, body }: { height: number; body?: 'number' | 'chart' }): ReactElement {
    const styles = useStyles()
    return (
        <View style={[styles.card, { height }]}>
            <View style={styles.head}>
                <View style={[styles.block, styles.icon]} />
                <View style={styles.lines}>
                    <View style={[styles.block, styles.line]} />
                    <View style={[styles.block, styles.lineShort]} />
                </View>
            </View>
            {body === 'number' ? (
                <View style={styles.numberBody}>
                    <View style={[styles.block, styles.value]} />
                    <View style={[styles.block, styles.spark]} />
                </View>
            ) : null}
            {body === 'chart' ? <View style={[styles.block, styles.chart]} /> : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    root: {
        gap: 8,
    },
    block: {
        backgroundColor: colors.sunken,
        borderRadius: 8,
    },
    search: {
        height: 44,
        borderRadius: radii.card,
    },
    eyebrow: {
        width: 64,
        height: 12,
        marginTop: 26,
        marginBottom: 10,
        marginHorizontal: 4,
    },
    cards: {
        gap: 8,
    },
    card: {
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.option,
        backgroundColor: colors.surface,
        paddingHorizontal: 12,
    },
    head: {
        height: 62,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
    },
    icon: {
        width: 34,
        height: 34,
        borderRadius: radii.markLarge,
    },
    lines: {
        gap: 8,
    },
    line: {
        width: 170,
        height: 12,
    },
    lineShort: {
        width: 110,
        height: 10,
    },
    numberBody: {
        flexDirection: 'row',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        paddingHorizontal: 2,
    },
    value: {
        width: 130,
        height: 30,
    },
    spark: {
        width: 120,
        height: 36,
    },
    chart: {
        flex: 1,
        marginHorizontal: 2,
        marginBottom: 14,
    },
}))
