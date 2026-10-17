import type { ReactElement, ReactNode } from 'react'
import { StyleSheet, View } from 'react-native'

import { colors, radii } from './tokens'

interface IconTileProps {
    children: ReactNode
    muted?: boolean
}

export function IconTile({ children, muted = false }: IconTileProps): ReactElement {
    return <View style={[styles.tile, muted && styles.muted]}>{children}</View>
}

const styles = StyleSheet.create({
    // 38pt content box plus a 1pt border on each side, as the prototype renders it.
    tile: {
        width: 40,
        height: 40,
        borderRadius: radii.tile,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    muted: {
        backgroundColor: colors.pressed,
    },
})
