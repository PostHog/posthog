import type { ReactElement } from 'react'
import { Text, type TextProps } from 'react-native'

import { useColors } from './theme'
import { type } from './tokens'

interface MonoTextProps extends TextProps {
    size?: 11 | 12
    color?: string
}

export function MonoText({ size = 12, color, style, ...rest }: MonoTextProps): ReactElement {
    const colors = useColors()
    return <Text {...rest} style={[size === 12 ? type.mono : type.monoSmall, { color: color ?? colors.ink }, style]} />
}
