import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { NumberDelta } from '@/model/views'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { createStyles, useColors } from '@/ui/theme'
import { radii } from '@/ui/tokens'

import { deltaText } from './snapshotChart'

interface DeltaPillProps {
    delta: NumberDelta
    formatValue: (value: number) => string
    /** Spoken after the change, such as "vs Oct 12". */
    basis: string
    testID?: string
}

/** The change as a screen reader says it: "Up 12.4% vs previous period". */
export function deltaSpoken(delta: NumberDelta, formatValue: (value: number) => string, basis: string): string {
    const text = deltaText(delta, formatValue)
    const direction = delta.change > 0 ? 'Up' : delta.change < 0 ? 'Down' : null
    return direction ? `${direction} ${text.slice(1)} ${basis}` : `${text} ${basis}`
}

/**
 * The change next to a big number. It stays neutral gray: the app does not know whether up is good for this metric.
 */
export function DeltaPill({ delta, formatValue, basis, testID }: DeltaPillProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const text = deltaText(delta, formatValue)
    const direction = delta.change > 0 ? 'up' : delta.change < 0 ? 'down' : null
    return (
        <View
            style={styles.pill}
            accessible
            accessibilityLabel={deltaSpoken(delta, formatValue, basis)}
            testID={testID}
        >
            {direction ? (
                <View style={direction === 'down' ? styles.down : undefined}>
                    <ArrowUpIcon size={10} color={colors.muted} strokeWidth={3.6} />
                </View>
            ) : null}
            <Text style={styles.text}>{text}</Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    pill: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 3,
        height: 22,
        paddingLeft: 7,
        paddingRight: 8,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
    },
    down: {
        transform: [{ rotate: '180deg' }],
    },
    text: {
        fontSize: 12,
        fontWeight: '600',
        color: colors.muted,
        fontVariant: ['tabular-nums'],
    },
}))
