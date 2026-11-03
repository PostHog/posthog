import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { Dot } from './Dot'
import { useColors } from './theme'
import { type } from './tokens'

interface EyebrowProps {
    children: string
    color?: string
    withDot?: boolean
}

export function Eyebrow({ children, color: colorProp, withDot = false }: EyebrowProps): ReactElement {
    const colors = useColors()
    const color = colorProp ?? colors.tertiary
    return (
        <View style={styles.row}>
            {withDot ? <Dot color={color} /> : null}
            <Text style={[type.eyebrow, styles.text, { color }]} numberOfLines={1}>
                {children}
            </Text>
        </View>
    )
}

const styles = StyleSheet.create({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    text: {
        textTransform: 'uppercase',
    },
})
