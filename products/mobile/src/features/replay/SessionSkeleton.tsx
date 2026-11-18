import type { ReactElement } from 'react'
import { type DimensionValue, View } from 'react-native'

import { createStyles } from '@/ui/theme'
import { radii } from '@/ui/tokens'

function Bar({ width, height = 14 }: { width: DimensionValue; height?: number }): ReactElement {
    const styles = useStyles()
    return <View style={[styles.bar, { width, height }]} />
}

export function SessionSkeleton(): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.root} accessibilityLabel="Loading the session" accessibilityRole="progressbar">
            <Bar width="40%" height={12} />
            <Bar width="90%" height={24} />
            <Bar width="70%" height={24} />
            <Bar width="80%" />
            <View style={styles.card}>
                <Bar width="30%" height={12} />
                <Bar width="100%" />
                <Bar width="95%" />
                <Bar width="60%" />
            </View>
            <Bar width="35%" height={12} />
            <Bar width="75%" />
            <Bar width="55%" />
        </View>
    )
}

export function SessionRowSkeleton(): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.row}>
            <View style={styles.thumb} />
            <View style={styles.rowBody}>
                <Bar width="85%" height={16} />
                <Bar width="55%" height={12} />
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
        marginVertical: 8,
        padding: 16,
        borderRadius: radii.softCard,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingVertical: 14,
    },
    thumb: {
        width: 80,
        height: 50,
        borderRadius: radii.tile,
        backgroundColor: colors.sunken,
    },
    rowBody: {
        flex: 1,
        gap: 8,
    },
}))
