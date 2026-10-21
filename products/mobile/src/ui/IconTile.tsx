import type { ReactElement, ReactNode } from 'react'
import { View } from 'react-native'

import { createStyles } from './theme'
import { radii } from './tokens'

interface IconTileProps {
    children: ReactNode
    muted?: boolean
}

export function IconTile({ children, muted = false }: IconTileProps): ReactElement {
    const styles = useStyles()
    return <View style={[styles.tile, muted && styles.muted]}>{children}</View>
}

const useStyles = createStyles(({ colors }) => ({
    // 38pt content box plus a 1pt border on each side, as the prototype renders it.
    tile: {
        width: 40,
        height: 40,
        borderRadius: radii.tile,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    muted: {
        backgroundColor: colors.pressed,
    },
}))
