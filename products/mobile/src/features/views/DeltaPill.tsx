import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import type { NumberDelta } from '@/model/views'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { colors, radii } from '@/ui/tokens'

import { deltaText } from './snapshotChart'

interface DeltaPillProps {
    delta: NumberDelta
    formatValue: (value: number) => string
    /** Spoken after the change, such as "vs Oct 12". */
    basis: string
    testID?: string
}

/**
 * The change next to a big number. It stays neutral gray: the app does not know whether up is good for this metric.
 */
export function DeltaPill({ delta, formatValue, basis, testID }: DeltaPillProps): ReactElement {
    const text = deltaText(delta, formatValue)
    const direction = delta.change > 0 ? 'Up' : delta.change < 0 ? 'Down' : null
    return (
        <View
            style={styles.pill}
            accessible
            accessibilityLabel={direction ? `${direction} ${text.slice(1)} ${basis}` : `${text} ${basis}`}
            testID={testID}
        >
            {direction ? (
                <View style={direction === 'Down' ? styles.down : undefined}>
                    <ArrowUpIcon size={13} color={colors.muted} strokeWidth={2.6} />
                </View>
            ) : null}
            <Text style={styles.text}>{text}</Text>
        </View>
    )
}

const styles = StyleSheet.create({
    pill: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        height: 26,
        paddingHorizontal: 9,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
    },
    down: {
        transform: [{ rotate: '180deg' }],
    },
    text: {
        fontSize: 14,
        lineHeight: 18,
        fontWeight: '600',
        color: colors.muted,
        fontVariant: ['tabular-nums'],
    },
})
