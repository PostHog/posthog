import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface LiveMeanwhileRowProps {
    icon: ReactNode
    title: string
    subtitle: string | null
    /** The value and sparkline of a pin, or the unread dot and chevron of the inbox. */
    trailing: ReactNode
    accessibilityLabel: string
    onPress: () => void
    testID: string
}

/** One compact row of the Meanwhile card: an icon tile, a title and subtitle, and what sits at the end. */
export function LiveMeanwhileRow({
    icon,
    title,
    subtitle,
    trailing,
    accessibilityLabel,
    onPress,
    testID,
}: LiveMeanwhileRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityLabel={accessibilityLabel}
            pressedBackground={colors.sunken}
            hitSlop={0}
            style={styles.row}
            testID={testID}
        >
            <View style={styles.iconTile}>{icon}</View>
            <View style={styles.text}>
                <Text style={styles.title} numberOfLines={1}>
                    {title}
                </Text>
                {subtitle ? (
                    <Text style={styles.subtitle} numberOfLines={1}>
                        {subtitle}
                    </Text>
                ) : null}
            </View>
            {trailing}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        minHeight: 64,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 10,
        paddingHorizontal: 12,
    },
    iconTile: {
        width: 34,
        height: 34,
        borderRadius: radii.markLarge,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    text: {
        flex: 1,
        minWidth: 0,
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
    },
    subtitle: {
        ...type.meta,
        color: colors.tertiary,
    },
}))
