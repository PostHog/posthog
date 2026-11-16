import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { lineHeight } from '@/ui/tokens'

import { formatPagerDate } from './chartMath'
import type { ChartInterval } from './types'

interface ChartDatePagerProps {
    from: number
    to: number
    interval: ChartInterval
    earlier: boolean
    later: boolean
    onEarlier: () => void
    onLater: () => void
}

export function ChartDatePager({
    from,
    to,
    interval,
    earlier,
    later,
    onEarlier,
    onLater,
}: ChartDatePagerProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.row}>
            <Pressable44
                onPress={onEarlier}
                disabled={!earlier}
                accessibilityLabel="Show earlier dates"
                accessibilityState={{ disabled: !earlier }}
                style={styles.button}
                testID="chart-dates-earlier"
            >
                <ChevronLeftIcon size={18} color={earlier ? colors.ink : colors.disabled} />
            </Pressable44>
            <Text style={styles.label} accessibilityLiveRegion="polite" numberOfLines={1}>
                {formatPagerDate(from, interval)} - {formatPagerDate(to, interval)}
            </Text>
            <Pressable44
                onPress={onLater}
                disabled={!later}
                accessibilityLabel="Show later dates"
                accessibilityState={{ disabled: !later }}
                style={styles.button}
                testID="chart-dates-later"
            >
                <ChevronRightIcon size={18} color={later ? colors.ink : colors.disabled} />
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', height: 44 },
    button: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
    label: { fontSize: 13, lineHeight: lineHeight(13), color: colors.secondary, flexShrink: 1 },
}))
