import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

interface SheetPageHeaderProps {
    title: string
    onBack: () => void
    testID: string
}

export function SheetPageHeader({ title, onBack, testID }: SheetPageHeaderProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.row}>
            <Pressable44
                onPress={onBack}
                accessibilityLabel="Back"
                pressedBackground={colors.sunken}
                style={styles.back}
                testID={`${testID}-back`}
            >
                <ChevronLeftIcon size={iconSizes.control} />
            </Pressable44>
            <Text style={styles.title} accessibilityRole="header" numberOfLines={1}>
                {title}
            </Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        marginTop: 10,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    back: {
        width: 44,
        height: 44,
        borderRadius: 22,
        alignItems: 'center',
        justifyContent: 'center',
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        flex: 1,
    },
}))
