import type { ReactElement } from 'react'
import { type DimensionValue, View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { radii } from '@/ui/tokens'

function Bar({ width, height = 14 }: { width: DimensionValue; height?: number }): ReactElement {
    const styles = useStyles()
    return <View style={[styles.bar, { width, height }]} />
}

/** The detail's shape while the experiment loads: header, hypothesis, status, progress and one metric card. */
export function ExperimentSkeleton(): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.root} accessibilityLabel="Loading the experiment" accessibilityRole="progressbar">
            <Bar width="45%" height={12} />
            <Bar width="80%" height={26} />
            <Bar width="60%" />
            <Bar width="75%" />
            <View style={styles.card}>
                <Bar width="25%" height={12} />
                <Bar width="100%" />
                <Bar width="70%" />
            </View>
            <View style={styles.card}>
                <Bar width="65%" />
            </View>
            <Bar width="30%" height={12} />
            <View style={styles.card}>
                <Bar width="100%" height={8} />
            </View>
            <Bar width="35%" height={12} />
            <View style={styles.card}>
                <Bar width="50%" height={16} />
                <View style={styles.cells}>
                    <View style={styles.cell} />
                    <View style={styles.cell} />
                    <View style={styles.cell} />
                </View>
                <View style={styles.cells}>
                    <View style={styles.cell} />
                    <View style={styles.cell} />
                    <View style={styles.cell} />
                </View>
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    root: {
        gap: 12,
    },
    bar: {
        borderRadius: 6,
        backgroundColor: colors.sunken,
    },
    card: {
        gap: 10,
        padding: 14,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    cells: {
        flexDirection: 'row',
        gap: 8,
    },
    cell: {
        flex: 1,
        height: 52,
        borderRadius: 10,
        backgroundColor: colors.sunken,
    },
}))
