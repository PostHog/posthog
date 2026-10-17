import type { ReactElement } from 'react'
import { View } from 'react-native'

interface DotProps {
    color: string
    size?: number
}

export function Dot({ color, size = 7 }: DotProps): ReactElement {
    return <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: color }} />
}
