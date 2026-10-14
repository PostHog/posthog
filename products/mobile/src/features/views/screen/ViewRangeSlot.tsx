import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { colors, radii, type } from '@/ui/tokens'

interface ViewRangeSlotProps {
    /** `range.label`. Null on a dashboard without saved dates, where each tile keeps its own range. */
    label: string | null
}

/**
 * The date range in a view header. It shows the range the view reads; picking another range belongs to the range
 * control that replaces this slot.
 */
export function ViewRangeSlot({ label }: ViewRangeSlotProps): ReactElement {
    const text = label ?? "Each tile's own range"
    return (
        <View style={styles.row}>
            <View style={styles.range} accessible accessibilityLabel={`Date range: ${text}`} testID="view-range">
                <Text style={styles.text} numberOfLines={1}>
                    {text}
                </Text>
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        marginTop: 14,
    },
    range: {
        height: 40,
        maxWidth: '100%',
        justifyContent: 'center',
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
    },
    text: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
