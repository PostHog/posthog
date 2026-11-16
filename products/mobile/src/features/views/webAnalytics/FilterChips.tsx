import type { ReactElement } from 'react'
import { ScrollView, Text, View } from 'react-native'

import type { WebFilter } from '@/model/views'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface FilterChipsProps {
    filters: readonly WebFilter[]
    onRemove: (id: string) => void
    onClear: () => void
}

/** "Clear all" stays at the right edge while the chips scroll. */
export function FilterChips({ filters, onRemove, onClear }: FilterChipsProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (filters.length === 0) {
        return null
    }
    return (
        <View style={styles.row} testID="web-filters">
            <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                style={styles.scroll}
                contentContainerStyle={styles.chips}
            >
                {filters.map((filter) => (
                    <Pressable44
                        key={filter.id}
                        onPress={() => onRemove(filter.id)}
                        accessibilityLabel={`Remove filter ${filter.label}: ${filter.value}`}
                        pressedBackground={colors.pressed}
                        style={styles.chip}
                        testID={`web-filter-${filter.id}`}
                    >
                        <Text style={styles.chipText} numberOfLines={1}>
                            <Text style={styles.chipLabel}>{filter.label}: </Text>
                            {filter.value}
                        </Text>
                        <CloseIcon size={12} color={colors.secondary} />
                    </Pressable44>
                ))}
            </ScrollView>
            <Pressable44
                onPress={onClear}
                accessibilityLabel="Clear all filters"
                style={styles.clear}
                testID="web-filters-clear"
            >
                <Text style={styles.clearText}>Clear all</Text>
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        marginBottom: 12,
    },
    scroll: {
        flex: 1,
    },
    chips: {
        gap: 8,
    },
    chip: {
        maxWidth: 260,
        height: 34,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    chipText: {
        ...type.metaSmall,
        flexShrink: 1,
        fontWeight: '600',
        color: colors.ink,
    },
    chipLabel: {
        fontWeight: '400',
        color: colors.secondary,
    },
    clear: {
        height: 34,
        justifyContent: 'center',
        paddingHorizontal: 4,
    },
    clearText: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.blue,
    },
}))
