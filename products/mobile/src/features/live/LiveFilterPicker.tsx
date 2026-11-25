import { type ReactElement, useMemo, useState } from 'react'
import { FlatList, Text, View } from 'react-native'
import { GestureDetector } from 'react-native-gesture-handler'
import { countryFlag, countryName } from '@/model/adapters/webAnalyticsBreakdowns'
import { COUNTRY_NAMES } from '@/model/countries'
import { LIVE_CHANNEL_TYPES, LIVE_DEVICE_TYPES } from '@/model/liveTrafficFilters'
import type { NativeGesture } from '@/ui/gestureTypes'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SearchField } from '@/ui/SearchField'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'
import { useSceneDimensions } from '@/ui/useSceneDimensions'

type PickerField = 'countryCode' | 'channelType' | 'deviceType'

interface Choice {
    value: string
    label: string
    description?: string
}

function choicesFor(field: PickerField, selected: string): Choice[] {
    if (field === 'countryCode') {
        return Object.keys(COUNTRY_NAMES)
            .map((value) => ({ value, label: countryName(value), description: value }))
            .sort((left, right) => left.label.localeCompare(right.label))
    }
    const labels: readonly string[] = field === 'channelType' ? LIVE_CHANNEL_TYPES : LIVE_DEVICE_TYPES
    const choices = labels.includes(selected) || !selected ? labels : [selected, ...labels]
    return choices.map((value) => ({ value, label: value }))
}

export function LiveFilterPicker({
    field,
    value,
    onChoose,
    gesture,
}: {
    field: PickerField
    value: string
    onChoose: (value: string) => void
    gesture: NativeGesture
}): ReactElement {
    const [search, setSearch] = useState('')
    const colors = useColors()
    const styles = useStyles()
    const { height } = useSceneDimensions()
    const choices = useMemo(() => choicesFor(field, value), [field, value])
    const query = search.trim().toLowerCase()
    const visible = choices.filter(
        (choice) => choice.value.toLowerCase().includes(query) || choice.label.toLowerCase().includes(query)
    )
    if (query && field === 'countryCode') {
        visible.sort(
            (left, right) => Number(right.value.toLowerCase() === query) - Number(left.value.toLowerCase() === query)
        )
    }
    if (query && field === 'channelType' && !choices.some((choice) => choice.label.toLowerCase() === query)) {
        visible.push({ value: search.trim(), label: search.trim(), description: 'Custom channel' })
    }
    if (!query)
        visible.unshift({
            value: '',
            label:
                field === 'countryCode'
                    ? 'All countries'
                    : field === 'deviceType'
                      ? 'All device types'
                      : 'All channels',
        })
    return (
        <>
            {field !== 'deviceType' ? (
                <View style={styles.search}>
                    <SearchField
                        value={search}
                        onChangeText={setSearch}
                        placeholder={
                            field === 'countryCode' ? 'Search by country or code' : 'Search or enter a custom channel'
                        }
                        testID="live-filter-search"
                    />
                </View>
            ) : null}
            <GestureDetector gesture={gesture}>
                <FlatList
                    style={{ maxHeight: height * 0.6, flexGrow: 0, flexShrink: 1 }}
                    keyboardShouldPersistTaps="handled"
                    data={visible}
                    keyExtractor={(item) => item.value}
                    ListEmptyComponent={<Text style={styles.empty}>No matching countries</Text>}
                    renderItem={({ item }) => (
                        <Pressable44
                            onPress={() => onChoose(item.value)}
                            hitSlop={0}
                            accessibilityRole="radio"
                            accessibilityLabel={item.description ? `${item.label}, ${item.description}` : item.label}
                            accessibilityState={{ checked: item.value === value }}
                            style={styles.row}
                            pressedBackground={colors.pressed}
                            testID={`live-filter-option-${item.value || 'any'}`}
                        >
                            {field === 'countryCode' && item.value ? (
                                <Text style={styles.flag}>{countryFlag(item.value)}</Text>
                            ) : null}
                            <Text style={styles.label}>{item.label}</Text>
                            {item.description ? <Text style={styles.meta}>{item.description}</Text> : null}
                            {item.value === value ? <CheckIcon size={16} color={colors.blue} /> : null}
                        </Pressable44>
                    )}
                />
            </GestureDetector>
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    search: { marginTop: 8, marginBottom: 10 },
    row: {
        minHeight: 48,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 6,
        paddingVertical: 8,
        borderBottomWidth: 1,
        borderColor: colors.rowDivider,
    },
    flag: { fontSize: 19 },
    label: { ...type.body, color: colors.ink, flexShrink: 1, flexGrow: 1 },
    meta: { ...type.meta, color: colors.secondary },
    empty: { ...type.bodySmall, color: colors.secondary, paddingVertical: 24, textAlign: 'center' },
}))
