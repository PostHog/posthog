import type { ReactElement, ReactNode } from 'react'
import { type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native'

import { colors, radii } from './tokens'

interface PillControlProps {
    children: ReactNode
    height?: number
    style?: StyleProp<ViewStyle>
}

export function PillControl({ children, height = 54, style }: PillControlProps): ReactElement {
    return <View style={[styles.pill, { height }, style]}>{children}</View>
}

const styles = StyleSheet.create({
    pill: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        paddingVertical: 4,
        paddingHorizontal: 6,
    },
})
