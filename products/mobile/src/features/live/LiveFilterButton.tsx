import { Stack } from 'expo-router'
import type { ReactElement } from 'react'
import { Text } from 'react-native'

import { FilterIcon } from '@/ui/icons/FilterIcon'
import { nativeIcons } from '@/ui/icons/nativeIcons'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface FilterButtonProps {
    count: number
    onPress: () => void
}

function filterLabel(count: number): string {
    return count ? `Live filters, ${count} active` : 'Live filters'
}

export function LiveFilterButton({ count, onPress }: FilterButtonProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityLabel={filterLabel(count)}
            pressedBackground={colors.background}
            style={styles.button}
            testID="live-filter-button"
        >
            <FilterIcon size={20} color={colors.ink} />
            <Text style={styles.text}>{count ? `Filters · ${count}` : 'Filters'}</Text>
        </Pressable44>
    )
}

// Expo Router reads the toolbar button element directly when it configures the native header.
export function liveNativeFilterButton({ count, onPress }: FilterButtonProps): ReactElement {
    return (
        <Stack.Toolbar.Button
            key="live-filters"
            iconRenderingMode="template"
            icon={nativeIcons.filter}
            accessibilityLabel={filterLabel(count)}
            onPress={onPress}
        >
            {count > 0 ? <Stack.Toolbar.Badge>{String(count)}</Stack.Toolbar.Badge> : null}
        </Stack.Toolbar.Button>
    )
}

const useStyles = createStyles(({ colors }) => ({
    button: {
        minHeight: 44,
        paddingHorizontal: 12,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        borderRadius: radii.pill,
    },
    text: { ...type.buttonSmall, color: colors.ink },
}))
