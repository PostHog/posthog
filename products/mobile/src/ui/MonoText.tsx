import type { ReactElement } from 'react'
import { Text, type TextProps } from 'react-native'

import { colors, type } from './tokens'

interface MonoTextProps extends TextProps {
    size?: 11 | 12
    color?: string
}

export function MonoText({ size = 12, color = colors.ink, style, ...rest }: MonoTextProps): ReactElement {
    return <Text {...rest} style={[size === 12 ? type.mono : type.monoSmall, { color }, style]} />
}
