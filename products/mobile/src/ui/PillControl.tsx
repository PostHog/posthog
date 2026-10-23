import type { ReactElement, ReactNode } from 'react'
import { type StyleProp, View, type ViewStyle } from 'react-native'

import { createStyles } from './theme'
import { radii } from './tokens'

interface PillControlProps {
    children: ReactNode
    height?: number
    style?: StyleProp<ViewStyle>
}

export function PillControl({ children, height = 54, style }: PillControlProps): ReactElement {
    const styles = useStyles()
    return <View style={[styles.pill, { height }, style]}>{children}</View>
}

const useStyles = createStyles(({ colors }) => ({
    pill: {
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.pill,
        paddingVertical: 4,
        paddingHorizontal: 6,
    },
}))
