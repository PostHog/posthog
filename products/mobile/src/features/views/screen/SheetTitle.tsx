import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface SheetTitleProps {
    title: string
    /** The small line above the title, such as the chart's name. */
    subtitle?: string | null
    onDone: () => void
}

/** The head of a Views sheet: a small line, the title, and Done. */
export function SheetTitle({ title, subtitle, onDone }: SheetTitleProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.head}>
            <View style={styles.titles}>
                {subtitle ? (
                    <Text style={styles.subtitle} numberOfLines={1}>
                        {subtitle}
                    </Text>
                ) : null}
                <Text style={styles.title} accessibilityRole="header">
                    {title}
                </Text>
            </View>
            <Pressable44 onPress={onDone} style={styles.done} pressedBackground={colors.pressed} testID="sheet-done">
                <Text style={styles.doneText}>Done</Text>
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    head: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        paddingTop: 10,
        paddingBottom: 12,
        paddingHorizontal: 4,
    },
    titles: {
        flex: 1,
        minWidth: 0,
    },
    subtitle: {
        ...type.meta,
        color: colors.tertiary,
    },
    title: {
        ...type.sheetTitleLarge,
        color: colors.ink,
    },
    done: {
        height: 36,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    doneText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
