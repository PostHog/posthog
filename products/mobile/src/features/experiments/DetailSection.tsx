import type { ReactElement, ReactNode } from 'react'
import { Text, View } from 'react-native'

import { Eyebrow } from '@/ui/Eyebrow'
import { createStyles, useTheme } from '@/ui/theme'
import { type } from '@/ui/tokens'

/** An eyebrow heading with an optional quiet aside, over the section's cards. */
export function DetailSection({
    title,
    aside,
    children,
    testID,
}: {
    title: string
    aside?: string | null
    children: ReactNode
    testID?: string
}): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.section} testID={testID}>
            <View style={styles.header}>
                <Eyebrow>{title}</Eyebrow>
                {aside ? (
                    <Text style={styles.aside} numberOfLines={1}>
                        {aside}
                    </Text>
                ) : null}
            </View>
            {children}
        </View>
    )
}

/** The variant colors, the same series colors the web's results charts use. */
export function useVariantColor(): (index: number) => string {
    const { chartPalette } = useTheme()
    return (index: number): string => chartPalette[index % chartPalette.length] ?? chartPalette[0] ?? '#1D4AFF'
}

/** A small square in the variant's color, the legend mark next to a variant key. */
export function VariantSwatch({ colorIndex, size = 10 }: { colorIndex: number; size?: number }): ReactElement {
    const color = useVariantColor()(colorIndex)
    return <View style={{ width: size, height: size, borderRadius: 2, backgroundColor: color }} />
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 26,
        gap: 10,
    },
    header: {
        minHeight: 24,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        paddingHorizontal: 2,
    },
    aside: {
        ...type.meta,
        color: colors.tertiary,
        flexShrink: 1,
    },
}))
